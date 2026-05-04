"""Phase 47 Wave 1: Pre-Trade AI chat endpoint.

POST /api/v1/trades/<journal_id>/ai/chat
Stateless per turn: each request is a direct LLM call.
Persists exactly one envelope per turn (success | degraded | failure) with journal_id set.
Registered via webapp.add_url_rule() in ui_server.py (parametric URL).

Per OQ-6 (47-01-NOTES.md): execute_with_fallback is internal-only infra.
Chat handler calls _call_llm_direct() which wraps litellm.acompletion directly,
returning (response_text, telemetry_dict). Tests mock _call_llm_direct.
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


async def _call_llm_direct(
    system_prompt: str,
    user_prompt: str,
    model: str,
) -> tuple[str, dict]:
    """Make a direct stateless LLM call via litellm.acompletion.

    Returns:
        (response_text, telemetry_dict)

    telemetry_dict contains:
        model_used: str — model that responded
        fallback_used: bool — False for direct calls (no failover chain)
        cost: dict — empty in Wave 1 (cost tracking deferred)
        reason_chain: list — empty in Wave 1

    Raises:
        Exception — propagated to caller on LLM failure (triggers 502 path).
    """
    from litellm import acompletion  # type: ignore[import]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = await acompletion(
        model=model,
        messages=messages,
    )
    response_text: str = response.choices[0].message.content or ""
    telemetry = {
        "model_used": model,
        "fallback_used": False,
        "cost": {},
        "reason_chain": [],
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

        # Build prompts.
        try:
            system_prompt = _load_chat_evaluator_prompt()
        except Exception as exc:
            log.error("Failed to load chat_evaluator prompt: %s", exc)
            system_prompt = "You are a trade-setup evaluator. Assess the trader's setup carefully."

        user_prompt = _build_user_prompt(message, context, journal_id)
        model = _DEFAULT_CHAT_MODEL

        # Direct LLM call (stateless per-turn, per OQ-6 Wave 1 design).
        try:
            response_text, telemetry = await _call_llm_direct(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
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
