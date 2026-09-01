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

import asyncio
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
from core.agents.tier1_context import build_tier1_context

# Phase 71: dispatch helper. Use absolute import via importlib so the module
# loads cleanly both under namespace-package routing AND when the test harness
# loads chat.py by file path (parent package not set in that case).
try:  # pragma: no cover - simple import branch
    from api.v1.trades.ai._conversation_routing import (
        UnknownConversationType,
        conversation_type_to_profile,
    )
except ImportError:  # pragma: no cover - test-harness fallback path
    import importlib.util as _importlib_util
    _routing_path = Path(__file__).parent / "_conversation_routing.py"
    _spec = _importlib_util.spec_from_file_location(
        "_phase71_conversation_routing", _routing_path
    )
    _routing_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_routing_mod)
    UnknownConversationType = _routing_mod.UnknownConversationType
    conversation_type_to_profile = _routing_mod.conversation_type_to_profile

log = logging.getLogger(__name__)

# Path to the chat-evaluator system prompt addendum (Phase 47-03).
# Resolved relative to VM107 root at call time via get_abs_path.
_CHAT_EVALUATOR_PROMPT_REL = Path(
    "agents/agent0/prompts/agent.system.main.chat_evaluator.md"
)

# Default model: read from CHAT_MODEL env var, fallback to DeepSeek Flash.
# In production this is overridden via VM107's container env.
_DEFAULT_CHAT_MODEL = os.environ["CHAT_MODEL"]


def _load_chat_evaluator_prompt() -> str:
    """Load the chat-evaluator system prompt from the agent prompts directory."""
    from helpers.files import get_abs_path
    path = Path(get_abs_path(str(_CHAT_EVALUATOR_PROMPT_REL)))
    return path.read_text(encoding="utf-8")


def _build_user_prompt(message: str, context: dict, journal_id: str) -> str:
    """Build a structured user prompt with Tier-1 context block.

    Phase 47.2 (LOCKED): `context` is the curated dict produced by
    `core.agents.tier1_context.build_tier1_context(journal_id)` — NOT the
    inline payload sent by the frontend. Top-level keys are:
      trade_id, instrument, direction, strategy_id, last_evaluation,
      journal_metadata { timeframe, checklist_snapshot_text, entry_price,
                         stop_loss_price, take_profit_price }
    """
    journal_metadata = context.get("journal_metadata") or {}

    parts: list[str] = [f"Journal ID: {journal_id}"]
    if context.get("instrument"):
        parts.append(f"Instrument: {context['instrument']}")
    if context.get("direction"):
        parts.append(f"Direction: {context['direction']}")
    timeframe = journal_metadata.get("timeframe")
    if timeframe and timeframe != "NA":
        parts.append(f"Timeframe: {timeframe}")
    if context.get("strategy_id"):
        parts.append(f"Strategy: {context['strategy_id']}")

    entry_price = journal_metadata.get("entry_price")
    stop_loss_price = journal_metadata.get("stop_loss_price")
    take_profit_price = journal_metadata.get("take_profit_price")
    if entry_price is not None:
        parts.append(f"Entry: {entry_price}")
    if stop_loss_price is not None:
        parts.append(f"Stop loss: {stop_loss_price}")
    if take_profit_price is not None:
        parts.append(f"Take profit: {take_profit_price}")

    last_eval = context.get("last_evaluation")
    if last_eval:
        rec = last_eval.get("recommendation") or "n/a"
        score = last_eval.get("score")
        confidence = last_eval.get("confidence") or "n/a"
        score_str = str(score) if score is not None else "n/a"
        parts.append(
            f"\nLast formal evaluation: recommendation={rec}, "
            f"score={score_str}, confidence={confidence}"
        )

    snapshot = journal_metadata.get("checklist_snapshot_text")
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
    profile_name: str = "agent0",
    conversation_type: str | None = None,
) -> tuple[str, dict]:
    """Run the Coordinator monologue() for one chat turn.

    Bootstraps a minimal AgentContext with the resolved host-agent profile
    (mirror of Phase 44 _call_subordinate_sync). Pre-loads prior conversation
    history into the spawned agent. Adds the current user prompt. Runs
    monologue() so the host agent can:
      - call search_knowledge / document_query (Phase 42.1 KB)
      - call call_subordinate("idea_agent" | "strategy_agent") per Phase 44
      - apply the full host-agent prompt include chain

    Args:
      chat_evaluator_addendum: chat_evaluator.md content. Prepended to the
        user prompt so the trade-evaluator role tone applies in this turn.
      user_prompt: current turn's user content (instrument/strategy/message).
      history_envelopes: prior chat envelopes for this journal, ordered ASC
        by timestamp. Loaded into agent.history before monologue().
      profile_name: filesystem profile name to bootstrap. Defaults to
        ``"agent0"`` (Phase 47 pre_trade flow). Phase 71 Plan 02 routes the
        5 new conversation modes to per-mode host profiles
        (trade_auditor_agent / behavioral_mentor_agent / weekly_review_agent
        / macro_agent / research_chat_agent).
      conversation_type: Phase 71 mode label threaded into agent.data so
        downstream InvocationContext construction picks it up for envelope
        telemetry lineage. ``None`` preserves Phase 47 behavior.

    Returns:
      (response_text, telemetry) — telemetry follows Phase 44 carrier pattern
      plus a ``host_agent_id`` field carrying the resolved profile.

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

    # Bootstrap host agent at the resolved filesystem profile.
    config = initialize_agent()
    config.profile = profile_name  # Phase 71: dispatched per conversation_type

    ctx = AgentContext(config=config, name=f"chat_{uuid.uuid4().hex[:8]}")
    agent = ctx.agent0
    # Inject routing identity for affinity-map lookup (Phase 44 § Agent Identity).
    agent.data["agent_id"] = "agent_zero"
    # Phase 71: thread conversation_type into agent.data so agent.py's
    # InvocationContext construction (Phase 70.5) picks it up for envelope
    # telemetry. None preserves Phase 47 behavior.
    if conversation_type is not None:
        agent.data["conversation_type"] = conversation_type

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
        # Phase 71: surface the resolved host agent profile + mode for
        # envelope telemetry so the frontend / replay tooling can verify
        # the routing decision.
        "host_agent_id": profile_name,
        "conversation_type": conversation_type,
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

    def __init__(self, app=None, thread_lock=None) -> None:
        # Phase 155 (D-04): permit no-arg construction for unit-level dispatch
        # tests (the production dispatch in ui_server.py always passes the Flask
        # app + thread lock). ApiHandler only stores these two references.
        super().__init__(app, thread_lock)

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

    async def _handle_macro_ask(self, input: Input, request, conversation_type: str) -> Output:
        """Phase 155 (D-04): early-intercept branch for conversation_type == "macro_ask".

        Routes the user's macro question through the router → specialist fan-out →
        chief-economist synthesizer pipeline (``MacroAskExecutor``), then persists the
        composed answer via the existing one-envelope-per-turn ``build_envelope`` /
        ``write_envelope`` contract (status ∈ {success, degraded, failure}). Additive:
        the macro_chat coordinator-monologue path and the shared CONVERSATION_TYPES
        frozenset are left untouched (Pitfall 7, D-04).
        """
        # Lazy import so the tests monkeypatch the SAME class object, and the heavy
        # executor deps are not pulled at chat.py module-import time.
        from agents.macro_ask_executor.executor import MacroAskExecutor

        journal_id = (getattr(request, "view_args", None) or {}).get("journal_id", "").strip()
        message = (input.get("message", "") or input.get("query", "") or "").strip()

        # Tier-1 context is best-effort — the executor's router/pillar reads honestly
        # degrade when it is unavailable; never fail the turn on a context-build miss.
        context: dict = {}
        if journal_id:
            try:
                context = await build_tier1_context(journal_id)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "macro_ask: tier1 context build failed journal_id=%s: %s",
                    journal_id, exc,
                )

        task_id = f"chat-{uuid.uuid4().hex}"
        host_agent_id = "vm107.macro_ask_router"

        # run() is sync (it drives the async specialist batch internally via
        # asyncio.run(), 155-03). process() is an async coroutine already executing
        # inside a running event loop, so calling run() DIRECTLY would trip
        # ``RuntimeError: asyncio.run() cannot be called from a running event loop``
        # (CR-01). Offload it to a worker thread so its private loop is legal.
        # WR-03: guard the offload — a hard fault (the empty-plan fail-loud
        # ValueError, an executor raise, or the RuntimeError above if it ever
        # regressed) degrades THIS turn honestly into the failure envelope instead
        # of propagating as a bare HTTP 500. The fail-loud semantics INSIDE the
        # executor are untouched; the handler simply refuses to fabricate a success.
        executor = MacroAskExecutor()
        try:
            sections = await asyncio.to_thread(
                executor.run, query=message, context=context, journal_id=journal_id
            )
        except Exception as exc:  # noqa: BLE001 - honest turn-level degradation (WR-03)
            log.warning(
                "macro_ask: executor.run failed journal_id=%s: %s",
                journal_id, exc,
            )
            sections = {
                "status": "failure",
                "answer": "",
                "limitations": [f"internal error: {type(exc).__name__}"],
            }

        sections = sections if isinstance(sections, dict) else {}
        answer: str = sections.get("answer", "") or ""
        limitations = sections.get("limitations", []) or []
        # Map the executor's status hint onto the envelope status vocabulary; fall
        # back to a truthiness read so a fabricated success is never emitted (T-155-03).
        status = sections.get("status")
        if status not in {"success", "degraded", "failure"}:
            status = "success" if answer else "failure"

        # One envelope per turn — best-effort persistence: an envelope-store outage
        # must not drop the composed answer the caller already earned (AC#2). Chain
        # source_envelope_id to the prior macro_ask turn for this journal thread.
        env_id = None
        if journal_id:
            try:
                db = get_mongo_db()
                prev_doc = db["agent_envelopes"].find_one(
                    {"journal_id": journal_id, "agent_id": host_agent_id},
                    sort=[("timestamp", -1)],
                )
                source_env_id: str | None = (prev_doc or {}).get("envelope_id")
                env = build_envelope(
                    task_id=task_id,
                    parent_task_id=None,
                    agent_id=host_agent_id,
                    input_payload={
                        "message": message,
                        "context": context,
                        "conversation_type": conversation_type,
                    },
                    output_payload={"response": answer},
                    telemetry={
                        "host_agent_id": host_agent_id,
                        "conversation_type": conversation_type,
                    },
                    status=status,
                    source_envelope_id=source_env_id,
                    journal_id=journal_id,
                )
                env_id = write_envelope(db, env)
            except Exception as exc:  # pragma: no cover - defensive store path
                log.warning(
                    "macro_ask: envelope persist failed journal_id=%s: %s",
                    journal_id, exc,
                )

        http_status = 200 if status != "failure" else 502
        return Response(
            json.dumps({
                "response": answer,
                "limitations": limitations,
                "envelope_id": env_id,
                "status": status,
                "degraded": status == "degraded",
                "host_agent_id": host_agent_id,
                "conversation_type": conversation_type,
            }),
            http_status,
            mimetype="application/json",
        )

    async def process(self, input: Input, request) -> Output:  # type: ignore[override]
        # Phase 155 (D-04): parse conversation_type FIRST so the macro_ask fan-out
        # mode is early-intercepted BEFORE journal_id/message validation and BEFORE
        # conversation_type_to_profile(). This keeps the shared
        # fingpt_core.CONVERSATION_TYPES frozenset (vendored across VM100/101/102/
        # Dagster) untouched (Pitfall 7) and leaves the macro_chat coordinator-
        # monologue path additive/unchanged (low blast radius).
        raw_conversation_type = input.get("conversation_type")
        conversation_type: str | None = (
            raw_conversation_type.strip() if isinstance(raw_conversation_type, str) and raw_conversation_type.strip() else None
        )
        if conversation_type == "macro_ask":
            return await self._handle_macro_ask(input, request, conversation_type)

        # Extract journal_id from parametric URL segment.
        # NOTE (Phase 155 D-04): the two 422 guards below are gated on
        # ``request is not None``. In production the dispatch in ui_server.py ALWAYS
        # passes a live Flask Request, so both guards fire byte-for-byte as before —
        # the coordinator-monologue path is unchanged for every real request. The
        # ``request is None`` seam exists only for request-less unit-dispatch tests
        # (which exercise the routing decision, not the HTTP validation).
        journal_id = (getattr(request, "view_args", None) or {}).get("journal_id", "").strip()
        if not journal_id and request is not None:
            return Response(
                json.dumps({"error": "Missing journal_id"}),
                422,
                mimetype="application/json",
            )

        # Validate message is non-empty.
        message = (input.get("message", "") or "").strip()
        if not message and request is not None:
            return Response(
                json.dumps({"error": "Empty message — 'message' field is required and must be non-empty"}),
                422,
                mimetype="application/json",
            )

        # Phase 71 Plan 02: conversation_type parsed above; resolve it to a
        # host-agent profile via the single source-of-truth dispatch helper.
        # Unknown values return 400 (client error), preserving the 422 path for
        # malformed bodies and the 502 path for server failures.
        try:
            profile_name, _skill_addendum = conversation_type_to_profile(conversation_type)
        except UnknownConversationType as exc:
            return Response(
                json.dumps({
                    "error": "invalid_conversation_type",
                    "detail": str(exc),
                }),
                400,
                mimetype="application/json",
            )
        # Effective conversation_type for telemetry: when omitted the backward-
        # compatible default is pre_trade (Phase 47 flow).
        effective_conversation_type: str = conversation_type or "pre_trade"
        # host_agent_id used on envelopes — chat envelopes for pre_trade keep
        # the legacy "agent_zero" identity so Phase 47 history queries still
        # find them; non-pre_trade modes record the resolved profile name.
        host_agent_id: str = "agent_zero" if conversation_type is None else profile_name

        # Phase 47.2 (LOCKED): the chat handler builds Tier-1 context server-side
        # from journal_id. The inline `context` payload (Wave 1 frontend pattern)
        # is accepted for backward-compat but IGNORED for prompt build — Tier-1
        # owns context retrieval now. Plan 08 strips inline context from the
        # frontend; this 1-release window keeps the body schema compatible.
        inline_context = input.get("context")
        if inline_context:
            log.debug(
                "Phase 47.2: inline context payload received but ignored — "
                "Tier-1 builder owns context retrieval. journal_id=%s",
                journal_id,
            )
        task_id = f"chat-{uuid.uuid4().hex}"
        start = time.perf_counter()

        # Tier-1 context + envelope-store reads. Production (request is not None)
        # re-raises on any failure, preserving the existing 500 behavior EXACTLY.
        # The ``request is None`` branch is the request-less unit-dispatch seam:
        # it degrades to an empty context / empty history so the routing decision
        # (macro_chat → coordinator monologue) can be exercised without Mongo.
        try:
            context: dict = await build_tier1_context(journal_id)
        except Exception:
            if request is not None:
                raise
            context = {}

        db = None
        source_env_id: str | None = None
        history_envelopes: list[dict] = []
        try:
            db = get_mongo_db()
            # source_envelope_id: chain to the most recent envelope for this
            # journal thread. Phase 47 scopes history by agent_id="agent_zero"
            # (pre_trade); Phase 71 scopes per host_agent_id so each conversation
            # mode owns its own thread within the journal.
            prev_doc = db["agent_envelopes"].find_one(
                {"journal_id": journal_id, "agent_id": host_agent_id},
                sort=[("timestamp", -1)],
            )
            source_env_id = (prev_doc or {}).get("envelope_id")

            # Pull conversation history for this journal + host_agent thread
            # (ordered ASC by timestamp). Pre-loaded into the host agent's history
            # before monologue() runs so the LLM has context-aware continuity
            # across turns (HTTP layer remains stateless).
            history_cursor = db["agent_envelopes"].find(
                {"journal_id": journal_id, "agent_id": host_agent_id},
                sort=[("timestamp", 1)],
            )
            history_envelopes = list(history_cursor)
        except Exception:
            if request is not None:
                raise

        # Build prompts.
        try:
            chat_evaluator_addendum = _load_chat_evaluator_prompt()
        except Exception as exc:
            log.error("Failed to load chat_evaluator prompt: %s", exc)
            chat_evaluator_addendum = "You are a trade-setup evaluator. Assess the trader's setup carefully."

        user_prompt = _build_user_prompt(message, context, journal_id)

        # Coordinator monologue() — full Agent Zero runtime: tool dispatch
        # (search_knowledge, document_query, call_subordinate), host-agent
        # prompt include chain, KB routing rules. Bootstraps the resolved
        # profile via the same pattern as Phase 44 _call_subordinate_sync.
        # Phase 71: profile_name + conversation_type threaded through.
        try:
            response_text, telemetry = await _call_coordinator_monologue(
                chat_evaluator_addendum=chat_evaluator_addendum,
                user_prompt=user_prompt,
                history_envelopes=history_envelopes,
                profile_name=profile_name,
                conversation_type=conversation_type,
            )
        except Exception as exc:
            log.warning(
                "Chat LLM failure for journal_id=%s task_id=%s: %s",
                journal_id, task_id, exc,
            )
            env_id = None
            if request is not None and db is not None:
                env = build_envelope(
                    task_id=task_id,
                    parent_task_id=None,
                    agent_id=host_agent_id,
                    input_payload={
                        "message": message,
                        "context": context,
                        "conversation_type": effective_conversation_type,
                    },
                    output_payload={"error": str(exc)},
                    telemetry={
                        "host_agent_id": profile_name,
                        "conversation_type": conversation_type,
                    },
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
                    "host_agent_id": profile_name,
                    "conversation_type": effective_conversation_type,
                }),
                502,
                mimetype="application/json",
            )

        # Determine status from telemetry.
        fallback_used: bool = bool(
            (telemetry or {}).get("fallback_used", False)
        )
        status = "degraded" if fallback_used else "success"

        # Persist one envelope per turn. Skipped only on the request-less unit-
        # dispatch seam (request is None); production always carries a live Flask
        # Request and an initialized CapabilityRegistry / envelope store.
        env_id = None
        if request is not None and db is not None:
            env = build_envelope(
                task_id=task_id,
                parent_task_id=None,
                agent_id=host_agent_id,
                input_payload={
                    "message": message,
                    "context": context,
                    "conversation_type": effective_conversation_type,
                },
                output_payload={"response": response_text},
                telemetry=telemetry if isinstance(telemetry, dict) else {},
                status=status,
                source_envelope_id=source_env_id,
                journal_id=journal_id,
            )
            env_id = write_envelope(db, env)

        log.info(
            "Chat envelope persisted journal_id=%s envelope_id=%s status=%s "
            "host_agent=%s conversation_type=%s duration_ms=%d",
            journal_id, env_id, status,
            profile_name, effective_conversation_type,
            int((time.perf_counter() - start) * 1000),
        )

        return Response(
            json.dumps({
                "response": response_text,
                "envelope_id": env_id,
                "status": status,
                "degraded": fallback_used,
                # Phase 71: surface the routing decision so the frontend +
                # replay tooling can verify and chain follow-up turns.
                "host_agent_id": profile_name,
                "conversation_type": effective_conversation_type,
            }),
            200,
            mimetype="application/json",
        )
