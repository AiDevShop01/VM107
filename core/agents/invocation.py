"""Phase 44 typed agent invocation layer.

run_idea / run_strategy / is_substantive / route_coordinator_input
provide the typed Python entry points used by:
  - The HTTP endpoint (Plan 04) — external direct invocation
  - The Coordinator integration (Plan 05) — internal delegation path
  - Tests — pure unit tests with mocked _call_subordinate_sync

Resolves Research § 7 ambiguity: call_subordinate is a Tool class, not a function.
For now, _call_subordinate_sync is designed as a synchronous wrapper with late
imports to avoid circular dependencies. In production, it constructs a minimal
subordinate AgentContext and runs monologue() directly.

Retry policy (CONTEXT.md § Failure Handling):
  - If safe_parse returns PlainTextResult, retry EXACTLY ONCE.
  - On second PlainTextResult → raise *AgentDegradedError (fail fast).
  - PlainTextResult NEVER passes downstream to Strategy.

Re-exports IdeaAgentDegradedError and StrategyAgentDegradedError so callers
can import them from this module directly (convenience re-export).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Final, Optional

from core.contracts.schemas import Hypothesis, StrategySpec
from core.agents.structured_output import safe_parse, PlainTextResult
from core.agents.invocation_exceptions import (
    InvalidInputError,
    IdeaAgentDegradedError,
    StrategyAgentDegradedError,
)

# Re-export exceptions so callers can import from this module.
__all__ = [
    "is_substantive",
    "route_coordinator_input",
    "run_idea",
    "run_strategy",
    "MAX_PARALLEL_SUBAGENTS",
    "SUBSTANTIVE_KEYWORDS",
    "IdeaAgentDegradedError",
    "StrategyAgentDegradedError",
    "InvalidInputError",
    "_call_subordinate_sync",
]

log = logging.getLogger(__name__)

# Phase 44 sequential default — see CONTEXT.md § Concurrency.
MAX_PARALLEL_SUBAGENTS: Final[int] = 1

# Pre-classifier v1 keyword list (CONTEXT.md § Coordinator Role + Behavior).
# Upgrade to small LLM classifier deferred — see CONTEXT.md § Deferred Ideas.
SUBSTANTIVE_KEYWORDS: Final[frozenset[str]] = frozenset({
    "strategy",
    "idea",
    "hypothesis",
    "trade",
    "setup",
    "pattern",
})


# ---------------------------------------------------------------------------
# Pre-classifier
# ---------------------------------------------------------------------------

def is_substantive(input_text: str) -> bool:
    """Pre-classifier v1 — keyword heuristic.

    Returns True if input_text contains at least one SUBSTANTIVE_KEYWORDS token
    (case-insensitive). Returns False for empty strings or chitchat.

    Upgrade to small LLM classifier deferred (CONTEXT.md § Deferred Ideas).
    """
    if not input_text:
        return False
    lowered = input_text.lower()
    return any(k in lowered for k in SUBSTANTIVE_KEYWORDS)


def route_coordinator_input(input_text: str, *, agent: Any = None) -> Optional[str]:
    """Coordinator pre-classification routing.

    Returns None if the input is non-substantive (Coordinator handles directly
    via its own LLM reasoning — no delegation needed).

    Returns the raw string result from Idea Agent subordinate invocation if
    the input is substantive (signal: delegate to Idea Agent).

    Note: Full typed chain (run_idea → run_strategy) is the Coordinator's job
    after receiving the Hypothesis back. This function is the routing gate only.
    """
    if not is_substantive(input_text):
        return None
    # Substantive input: invoke Idea Agent subordinate and return raw output.
    # The Coordinator's prompt instructs it to then call run_strategy with the result.
    _sub_result = _call_subordinate_sync("idea_agent", input_text)
    if isinstance(_sub_result, tuple):
        raw, _telemetry = _sub_result
    else:
        raw = _sub_result
    return raw


# ---------------------------------------------------------------------------
# Internal subordinate invocation (sync wrapper)
# ---------------------------------------------------------------------------

def _call_subordinate_sync(
    profile: str,
    message: str,
    *,
    parent_context: Optional[Any] = None,
) -> tuple[str, dict]:
    """Invoke a subordinate Agent with the given profile and return (raw_output, telemetry).

    Synchronous wrapper. In production, constructs a minimal subordinate AgentContext
    using Agent Zero's existing primitives (Research § 7 resolution option 2).
    Late imports to avoid circular dependencies (agent.py → core → invocation).

    Returns:
        (raw_output, telemetry) where telemetry is a dict with:
            model_used, reason_chain, cost, fallback_used

    Raises:
        RuntimeError: If Agent Zero bootstrap fails.
    """
    # Late imports — avoid circular dependency: agent.py imports core; core must not
    # import agent.py at module level. See Research § 10 anti-pattern.
    try:
        from agent import Agent  # type: ignore[import]
        from agent_context import AgentContext  # type: ignore[import]
    except ImportError:
        # In unit-test environments, agent.py is not importable.
        # Tests mock _call_subordinate_sync directly — this path is never reached.
        raise RuntimeError(
            "_call_subordinate_sync requires Agent Zero runtime (agent.py). "
            "In tests, mock core.agents.invocation._call_subordinate_sync directly."
        )

    # Build minimal AgentContext using Agent Zero's profile system.
    # The profile parameter maps to agents/<profile>/ directory.
    # Agent Zero extensions (router, structured output) activate automatically.
    ctx = AgentContext.new(profile=profile, name=f"sub_{profile}_{uuid.uuid4().hex[:8]}")
    sub = ctx.agent0

    # Inject routing agent_id for affinity map lookup (CONTEXT § Agent Identity).
    from core.agents.tool_scope import resolve_agent_id_from_profile
    sub.data["agent_id"] = resolve_agent_id_from_profile(profile)

    import asyncio
    raw = asyncio.get_event_loop().run_until_complete(sub.monologue(message))

    # Capture router telemetry after monologue but before after-hooks clear it.
    # See Research § 13 OQ-4 and Phase 43.2 _router_log_cost.py carrier pattern.
    telemetry: dict = {
        "model_used": sub.data.get("_router_model_used", "unknown"),
        "reason_chain": sub.data.get("_router_reason_chain", []),
        "cost": sub.data.get("_router_cost_record", {}),
        "fallback_used": sub.data.get("_router_fallback_used", False),
    }

    return raw, telemetry


# ---------------------------------------------------------------------------
# Typed wrappers
# ---------------------------------------------------------------------------

def run_idea(
    input_text: str,
    *,
    db: Any = None,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> Hypothesis:
    """Invoke Idea Agent → Hypothesis (typed).

    Retry-once-then-fail policy (CONTEXT.md § Idea Agent):
      - On PlainTextResult from safe_parse: retry exactly once.
      - If second attempt also PlainTextResult: raise IdeaAgentDegradedError.
      - PlainTextResult NEVER passes downstream to Strategy Agent.

    On success, persists one AgentEnvelope to MongoDB (if db is provided) and
    returns a Hypothesis with source_envelope_id = the persisted envelope_id.

    Args:
        input_text: Substantive text to transform into a Hypothesis.
        db: MongoDB database handle. If None, envelope persistence is skipped
            (useful for unit tests and offline invocation).
        task_id: Phase 42 task identifier. Defaults to a generated UUID prefixed
            "api-" for direct HTTP calls (Research § OQ-6).
        parent_task_id: Optional parent task for nested invocation chains.

    Returns:
        Hypothesis with source_envelope_id populated to the successful envelope_id.

    Raises:
        IdeaAgentDegradedError: Both attempts returned PlainTextResult.
    """
    from core.agents.envelope_writer import build_envelope, write_envelope

    _task_id = task_id or f"api-{uuid.uuid4()}"

    attempt = 0
    while attempt < 2:
        attempt += 1
        _sub_result = _call_subordinate_sync("idea_agent", input_text)
        if isinstance(_sub_result, tuple):
            raw, telemetry = _sub_result
        else:
            raw, telemetry = _sub_result, {}
        result = safe_parse(raw, Hypothesis)

        if isinstance(result, Hypothesis):
            # Success — persist envelope, enrich Hypothesis with source_envelope_id.
            envelope_id: Optional[str] = None
            if db is not None:
                envelope = build_envelope(
                    task_id=_task_id,
                    parent_task_id=parent_task_id,
                    agent_id="idea_agent",
                    input_payload={"text": input_text},
                    output_payload=result.model_dump(),
                    telemetry=telemetry,
                    status="success",
                    source_envelope_id=None,
                )
                write_envelope(db, envelope)
                envelope_id = envelope.envelope_id

            # Hypothesis is frozen (BaseContract) — use model_copy to add envelope link.
            if envelope_id is not None:
                return result.model_copy(update={"source_envelope_id": envelope_id})
            return result

        # Degraded path — persist envelope per attempt, then retry.
        assert isinstance(result, PlainTextResult)
        log.warning(
            "idea_agent degraded on attempt %d/2 — error_chain=%s",
            attempt,
            result.error_chain,
        )
        if db is not None:
            envelope = build_envelope(
                task_id=_task_id,
                parent_task_id=parent_task_id,
                agent_id="idea_agent",
                input_payload={"text": input_text},
                output_payload={
                    "plain_text": result.raw_output,
                    "error_chain": result.error_chain,
                },
                telemetry=telemetry,
                status="degraded",
                source_envelope_id=None,
            )
            write_envelope(db, envelope)

    # Both attempts degraded — fail fast. PlainTextResult does NOT pass downstream.
    raise IdeaAgentDegradedError(
        error_chain=[f"attempt_{i + 1}_degraded" for i in range(2)]
    )


def run_strategy(
    hypothesis: Any,
    *,
    db: Any = None,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> StrategySpec:
    """Invoke Strategy Agent → StrategySpec (typed).

    Strict input contract (CONTEXT.md § Strategy Agent):
      'assert isinstance(input, Hypothesis). Reject anything else with
       InvalidInputError — NO auto-wrapping/auto-calling Idea Agent.'

    Same retry-once-then-fail policy as run_idea.

    Args:
        hypothesis: MUST be a Hypothesis instance. Any other type raises
            InvalidInputError immediately, before any LLM call.
        db: MongoDB database handle. If None, envelope persistence is skipped.
        task_id: Phase 42 task identifier. Defaults to generated UUID.
        parent_task_id: Optional parent task.

    Returns:
        StrategySpec.

    Raises:
        InvalidInputError: hypothesis is not a Hypothesis instance.
        StrategyAgentDegradedError: Both attempts returned PlainTextResult.
    """
    from core.agents.envelope_writer import build_envelope, write_envelope

    if not isinstance(hypothesis, Hypothesis):
        raise InvalidInputError(
            f"run_strategy requires a Hypothesis instance, got {type(hypothesis).__name__}. "
            f"Strategy Agent does NOT auto-call Idea Agent (CONTEXT.md § Strategy Agent). "
            f"Call run_idea() first and pass the resulting Hypothesis here."
        )

    _task_id = task_id or f"api-{uuid.uuid4()}"

    attempt = 0
    while attempt < 2:
        attempt += 1
        _sub_result = _call_subordinate_sync(
            "strategy_agent", hypothesis.model_dump_json()
        )
        if isinstance(_sub_result, tuple):
            raw, telemetry = _sub_result
        else:
            raw, telemetry = _sub_result, {}
        result = safe_parse(raw, StrategySpec)

        if isinstance(result, StrategySpec):
            if db is not None:
                envelope = build_envelope(
                    task_id=_task_id,
                    parent_task_id=parent_task_id,
                    agent_id="strategy_agent",
                    input_payload=hypothesis.model_dump(),
                    output_payload=result.model_dump(),
                    telemetry=telemetry,
                    status="success",
                    source_envelope_id=hypothesis.source_envelope_id,
                )
                write_envelope(db, envelope)
            return result

        # Degraded path.
        assert isinstance(result, PlainTextResult)
        log.warning(
            "strategy_agent degraded on attempt %d/2 — error_chain=%s",
            attempt,
            result.error_chain,
        )
        if db is not None:
            envelope = build_envelope(
                task_id=_task_id,
                parent_task_id=parent_task_id,
                agent_id="strategy_agent",
                input_payload=hypothesis.model_dump(),
                output_payload={
                    "plain_text": result.raw_output,
                    "error_chain": result.error_chain,
                },
                telemetry=telemetry,
                status="degraded",
                source_envelope_id=hypothesis.source_envelope_id,
            )
            write_envelope(db, envelope)

    raise StrategyAgentDegradedError(
        error_chain=[f"attempt_{i + 1}_degraded" for i in range(2)]
    )
