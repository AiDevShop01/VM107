"""Phase 47 Wave 1 (post-fix): Pre-Trade AI chat endpoint.

POST /api/v1/trades/<journal_id>/ai/chat

Stateless across HTTP turns (no persistent agent state between requests),
but each turn runs the full Coordinator (agent_zero profile) monologue() —
which gives the LLM access to:
  - search_knowledge / document_query (Phase 42.1 KB)
  - call_subordinate (delegate to idea_agent / strategy_agent per Phase 44)
  - the full Coordinator prompt include chain (role + specifics + KB routing)

Conversation history from prior turns is pulled from Mongo agent_envelopes
(filtered by journal_id) and pre-loaded into the spawned agent's history
before monologue() runs.

Persists exactly one envelope per turn (success | degraded | failure)
with journal_id set. Registered via webapp.add_url_rule() in ui_server.py.

Bootstrap pattern mirrors core/agents/invocation.py:_call_subordinate_sync
(Phase 44 commit c0b1fee), but uses agent_zero profile (not idea/strategy).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

from flask import Response, request as flask_request

from helpers.api import ApiHandler, Input, Output
from helpers.mongo import get_mongo_db
from core.agents.envelope_writer import build_envelope, write_envelope

log = logging.getLogger(__name__)

# Path to the chat-evaluator system prompt addendum (Phase 47-03).
# Resolved relative to VM107 root at call time via get_abs_path.
_CHAT_EVALUATOR_PROMPT_REL = Path(
    "agents/agent0/prompts/agent.system.main.chat_evaluator.md"
)

# Default model: read from CHAT_MODEL env var, fallback to DeepSeek Flash.
# In production this is overridden via VM107's container env.
_DEFAULT_CHAT_MODEL = os.environ.get("CHAT_MODEL", "deepseek/deepseek-v4-flash")


def _load_chat_evaluator_prompt() -> str:
    """Load the chat-evaluator system prompt from the agent prompts directory."""
    from helpers.files import get_abs_path
    path = Path(get_abs_path(str(_CHAT_EVALUATOR_PROMPT_REL)))
    return path.read_text(encoding="utf-8")


def _build_user_prompt(message: str, context: dict, journal_id: str) -> str:
    """Build a structured user prompt with inline context block."""
    parts: list[str] = [f"Journal ID: {journal_id}"]
    if context.get("instrument"):
        parts.append(f"Instrument: {context['instrument']}")
    timeframe = context.get("timeframe")
    if timeframe and timeframe != "NA":
        parts.append(f"Timeframe: {timeframe}")
    if context.get("strategy_id"):
        parts.append(f"Strategy: {context['strategy_id']}")
    snapshot = context.get("checklist_snapshot_text")
    if snapshot:
        parts.append(f"\nChecklist snapshot:\n{snapshot}")
    parts.append(f"\nTrader's message:\n{message}")
    return "\n".join(parts)


def _format_history_for_user_message(history_envelopes: list[dict]) -> str:
    """Format prior conversation envelopes as a text block to prepend to the
    current user message. Each envelope contributes one user→agent turn.

    History envelopes are ordered ASC by timestamp. Failure envelopes show as
    a bracketed marker so the agent knows past turns degraded.
    """
    if not history_envelopes:
        return ""
    lines: list[str] = ["Previous conversation in this trade setup:"]
    for env in history_envelopes:
        user_msg = ((env.get("input") or {}).get("message") or "").strip()
        if user_msg:
            lines.append(f"\n[Trader]: {user_msg}")
        if env.get("status") == "failure":
            lines.append("[Agent]: [response failed in a prior turn]")
        else:
            agent_resp = ((env.get("output") or {}).get("response") or "").strip()
            if agent_resp:
                lines.append(f"[Agent]: {agent_resp}")
    lines.append("\n---")
    return "\n".join(lines)


async def _call_coordinator_monologue(
    chat_evaluator_addendum: str,
    user_prompt: str,
    history_envelopes: list[dict],
) -> tuple[str, dict]:
    """Run the Coordinator (agent_zero profile) monologue() for one chat turn.

    Bootstraps a minimal AgentContext with the agent_zero profile (mirror of
    Phase 44 _call_subordinate_sync). Pre-loads prior conversation history
    into the spawned agent. Adds the current user prompt. Runs monologue()
    so the Coordinator can:
      - call search_knowledge / document_query (Phase 42.1 KB)
      - call call_subordinate("idea_agent" | "strategy_agent") per Phase 44
      - apply the full Coordinator prompt include chain

    Args:
      chat_evaluator_addendum: chat_evaluator.md content. Prepended to the
        user prompt so the trade-evaluator role tone applies in this turn.
      user_prompt: current turn's user content (instrument/strategy/message).
      history_envelopes: prior chat envelopes for this journal, ordered ASC
        by timestamp. Loaded into agent.history before monologue().

    Returns:
      (response_text, telemetry) — telemetry follows Phase 44 carrier pattern.

    Raises:
      Exception — propagated to caller on LLM/monologue failure (502 path).
    """
    # Late imports — avoid circular dependency: agent.py imports core.
    try:
        from agent import AgentContext, UserMessage  # type: ignore[import]
        from initialize import initialize_agent  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "Coordinator monologue() requires Agent Zero runtime (agent.py + initialize.py). "
            "In tests, mock _call_coordinator_monologue directly."
        ) from exc

    # Bootstrap Coordinator (agent_zero profile).
    config = initialize_agent()
    config.profile = "agent0"  # Coordinator filesystem profile name (Phase 44)

    ctx = AgentContext(config=config, name=f"chat_{uuid.uuid4().hex[:8]}")
    agent = ctx.agent0
    # Inject routing identity for affinity-map lookup (Phase 44 § Agent Identity).
    agent.data["agent_id"] = "agent_zero"

    # Pre-load prior conversation history. Agent Zero's monologue iterates
    # through agent.history; we add the prior turns as user messages so the
    # LLM sees them in-context. We also include agent responses inside the
    # formatted history block (passed as part of the *current* user message)
    # so prior assistant turns are preserved as context.
    history_block = _format_history_for_user_message(history_envelopes)
    composed_user = (
        f"{chat_evaluator_addendum}\n\n{history_block}\n\nCurrent turn:\n{user_prompt}"
        if history_block
        else f"{chat_evaluator_addendum}\n\nCurrent turn:\n{user_prompt}"
    )

    agent.hist_add_user_message(UserMessage(message=composed_user, attachments=[]))

    # Run Coordinator's full monologue — tool dispatch, search_knowledge,
    # call_subordinate are all available within this turn.
    try:
        response_text: str = await agent.monologue()
    finally:
        # Clean up: remove the spawned context so it doesn't leak.
        try:
            from agent import AgentContext as _AC  # type: ignore[import]
            with _AC._contexts_lock:  # type: ignore[attr-defined]
                _AC._contexts.pop(ctx.id, None)  # type: ignore[attr-defined]
        except Exception:
            pass  # best-effort cleanup

    # Capture router telemetry (Phase 43.2 carrier pattern).
    telemetry = {
        "model_used": agent.data.get("_router_model_used", "unknown"),
        "reason_chain": agent.data.get("_router_reason_chain", []),
        "cost": agent.data.get("_router_cost_record", {}),
        "fallback_used": agent.data.get("_router_fallback_used", False),
    }
    return response_text, telemetry


class TradeAiChat(ApiHandler):
    """POST /api/v1/trades/<journal_id>/ai/chat — stateless per-turn AI chat.

    Registered via webapp.add_url_rule() in helpers/ui_server.py.
    journal_id is read from request.view_args (Flask parametric URL).
    X-API-KEY authentication required.

    Wave 1 behaviour:
    - Direct LLM call (no AgentRunner, no call_subordinate).
    - System prompt: chat_evaluator.md + user prompt with inline context.
    - Every turn persists exactly one envelope (success | degraded | failure).
    - source_envelope_id chains to the prior envelope for this journal.
    - LLM failure → persist failure envelope → 502.
    """

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: Input, request) -> Output:  # type: ignore[override]
        # Extract journal_id from parametric URL segment.
        journal_id = (getattr(request, "view_args", None) or {}).get("journal_id", "").strip()
        if not journal_id:
            return Response(
                json.dumps({"error": "Missing journal_id"}),
                422,
                mimetype="application/json",
            )

        # Validate message is non-empty.
        message = (input.get("message", "") or "").strip()
        if not message:
            return Response(
                json.dumps({"error": "Empty message — 'message' field is required and must be non-empty"}),
                422,
                mimetype="application/json",
            )

        context: dict = input.get("context") or {}
        task_id = f"chat-{uuid.uuid4().hex}"
        db = get_mongo_db()
        start = time.perf_counter()

        # source_envelope_id: chain to the most recent envelope for this journal thread.
        prev_doc = db["agent_envelopes"].find_one(
            {"journal_id": journal_id, "agent_id": "agent_zero"},
            sort=[("timestamp", -1)],
        )
        source_env_id: str | None = (prev_doc or {}).get("envelope_id")

        # Pull full conversation history for this journal (ordered ASC by timestamp).
        # Pre-loaded into the Coordinator's history before monologue() runs so the
        # LLM has context-aware continuity across turns (HTTP layer remains stateless).
        history_cursor = db["agent_envelopes"].find(
            {"journal_id": journal_id, "agent_id": "agent_zero"},
            sort=[("timestamp", 1)],
        )
        history_envelopes: list[dict] = list(history_cursor)

        # Build prompts.
        try:
            chat_evaluator_addendum = _load_chat_evaluator_prompt()
        except Exception as exc:
            log.error("Failed to load chat_evaluator prompt: %s", exc)
            chat_evaluator_addendum = "You are a trade-setup evaluator. Assess the trader's setup carefully."

        user_prompt = _build_user_prompt(message, context, journal_id)

        # Coordinator monologue() — full Agent Zero runtime: tool dispatch
        # (search_knowledge, document_query, call_subordinate), Coordinator
        # prompt include chain, KB routing rules. Bootstraps agent_zero
        # profile via the same pattern as Phase 44 _call_subordinate_sync.
        try:
            response_text, telemetry = await _call_coordinator_monologue(
                chat_evaluator_addendum=chat_evaluator_addendum,
                user_prompt=user_prompt,
                history_envelopes=history_envelopes,
            )
        except Exception as exc:
            log.warning(
                "Chat LLM failure for journal_id=%s task_id=%s: %s",
                journal_id, task_id, exc,
            )
            env = build_envelope(
                task_id=task_id,
                parent_task_id=None,
                agent_id="agent_zero",
                input_payload={"message": message, "context": context},
                output_payload={"error": str(exc)},
                telemetry={},
                status="failure",
                source_envelope_id=source_env_id,
                journal_id=journal_id,
            )
            env_id = write_envelope(db, env)
            return Response(
                json.dumps({
                    "error": "LLM failure — AI service unavailable",
                    "envelope_id": env_id,
                    "status": "failure",
                }),
                502,
                mimetype="application/json",
            )

        # Determine status from telemetry.
        fallback_used: bool = bool(
            (telemetry or {}).get("fallback_used", False)
        )
        status = "degraded" if fallback_used else "success"

        env = build_envelope(
            task_id=task_id,
            parent_task_id=None,
            agent_id="agent_zero",
            input_payload={"message": message, "context": context},
            output_payload={"response": response_text},
            telemetry=telemetry if isinstance(telemetry, dict) else {},
            status=status,
            source_envelope_id=source_env_id,
            journal_id=journal_id,
        )
        env_id = write_envelope(db, env)

        log.info(
            "Chat envelope persisted journal_id=%s envelope_id=%s status=%s "
            "duration_ms=%d",
            journal_id, env_id, status,
            int((time.perf_counter() - start) * 1000),
        )

        return Response(
            json.dumps({
                "response": response_text,
                "envelope_id": env_id,
                "status": status,
                "degraded": fallback_used,
            }),
            200,
            mimetype="application/json",
        )
