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

from core.contracts.schemas import (
    BacktestResult,
    BuildReport,
    CodeModule,
    CriticVerdict,
    Hypothesis,
    RefinementContextEnvelope,
    RefinementLoopState,
    StrategySpec,
)
from core.agents.structured_output import safe_parse, PlainTextResult
from core.agents.invocation_exceptions import (
    BacktesterDegradedError,
    CodeAgentDegradedError,
    CriticDegradedError,
    IdeaAgentDegradedError,
    InvalidInputError,
    StrategyAgentDegradedError,
)

# Re-export exceptions so callers can import from this module.
__all__ = [
    "is_substantive",
    "route_coordinator_input",
    "run_idea",
    "run_strategy",
    "run_code",
    "run_build",
    "run_backtest",
    "run_critic",
    "MAX_PARALLEL_SUBAGENTS",
    "SUBSTANTIVE_KEYWORDS",
    "IdeaAgentDegradedError",
    "StrategyAgentDegradedError",
    "CodeAgentDegradedError",
    "BacktesterDegradedError",
    "CriticDegradedError",
    "InvalidInputError",
    "_call_subordinate_sync",
    "_invoke_build_agent",
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
    # import agent.py at module level.
    try:
        from agent import Agent, AgentContext, UserMessage  # type: ignore[import]
        from initialize import initialize_agent  # type: ignore[import]
    except ImportError:
        # In unit-test environments, agent.py is not importable.
        # Tests mock _call_subordinate_sync directly — this path is never reached.
        raise RuntimeError(
            "_call_subordinate_sync requires Agent Zero runtime (agent.py). "
            "In tests, mock core.agents.invocation._call_subordinate_sync directly."
        )

    # Build minimal AgentContext using Agent Zero's profile system.
    # Mirrors tools/call_subordinate.py:Delegation pattern, adapted for the
    # standalone HTTP-entry-point case (no parent agent context to inherit from).
    config = initialize_agent()
    config.profile = profile  # override default profile

    ctx = AgentContext(config=config, name=f"sub_{profile}_{uuid.uuid4().hex[:8]}")
    sub = ctx.agent0  # AgentContext.__init__ creates agent0 internally

    # Inject routing agent_id for affinity map lookup (CONTEXT § Agent Identity).
    from core.agents.tool_scope import resolve_agent_id_from_profile
    sub.data["agent_id"] = resolve_agent_id_from_profile(profile)

    # Add the user message to subordinate's history, then run its monologue.
    # Agent.monologue() takes no arguments — the message must be in history.
    sub.hist_add_user_message(UserMessage(message=message, attachments=[]))

    import asyncio
    # Called from a worker thread (Flask endpoint dispatches via run_in_executor),
    # so asyncio.run() is safe — creates a fresh event loop in this thread.
    raw = asyncio.run(sub.monologue())

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
        try:
            _sub_result = _call_subordinate_sync("idea_agent", input_text)
        except RuntimeError as e:
            # Bootstrap or runtime failure inside Agent Zero — won't recover via retry.
            # Surface as IdeaAgentDegradedError so callers get a typed exception and
            # the endpoint's failure-path persists an envelope.
            log.error("idea_agent bootstrap/runtime failure: %s", e, exc_info=True)
            raise IdeaAgentDegradedError(
                error_chain=[f"runtime_failure: {type(e).__name__}: {e}"]
            ) from e
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
    refinement_context: Optional[RefinementContextEnvelope] = None,
) -> StrategySpec:
    """Invoke Strategy Agent → StrategySpec (typed).

    Strict input contract (CONTEXT.md § Strategy Agent):
      'assert isinstance(input, Hypothesis). Reject anything else with
       InvalidInputError — NO auto-wrapping/auto-calling Idea Agent.'

    Same retry-once-then-fail policy as run_idea.

    Phase 48 Plan 48-01 — additive kwarg ``refinement_context``: when present
    (Phase 48 refinement loop, iteration > 0), the envelope is folded into the
    prompt payload so the Strategy Agent regenerates from the SAME immutable
    Hypothesis PLUS the prior critic's RefinementTargets. Default ``None``
    preserves Phase 44 call sites.

    Args:
        hypothesis: MUST be a Hypothesis instance. Any other type raises
            InvalidInputError immediately, before any LLM call.
        db: MongoDB database handle. If None, envelope persistence is skipped.
        task_id: Phase 42 task identifier. Defaults to generated UUID.
        parent_task_id: Optional parent task.
        refinement_context: Phase 48 RefinementContextEnvelope (optional).
            When set, the prompt-include helper threads it through verbatim.

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

    # Phase 48: fold refinement_context into the subordinate prompt as a typed
    # JSON envelope (NOT prose). Default empty when caller passes None.
    sub_payload = _build_strategy_prompt_payload(hypothesis, refinement_context)

    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            _sub_result = _call_subordinate_sync(
                "strategy_agent", sub_payload
            )
        except RuntimeError as e:
            log.error("strategy_agent bootstrap/runtime failure: %s", e, exc_info=True)
            raise StrategyAgentDegradedError(
                error_chain=[f"runtime_failure: {type(e).__name__}: {e}"]
            ) from e
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


# ---------------------------------------------------------------------------
# Phase 48 Plan 48-01 — typed wrappers for the refinement loop
# ---------------------------------------------------------------------------
#
# These four wrappers (run_code / run_build / run_backtest / run_critic) close
# the Phase 45 deferral and add the new Phase 48 critic. Patterns mirror
# run_idea / run_strategy:
#   - LLM-mediated wrappers use _call_subordinate_sync + safe_parse +
#     retry-once-then-fail.
#   - run_build is DETERMINISTIC (pure-Python service path — NO LLM, NO retry).
#   - Each wrapper threads refinement_context (where applicable) into the
#     prompt as a typed JSON envelope.
#   - Each LLM-mediated wrapper persists an AgentEnvelope (success or degraded)
#     when a `db` handle is provided.
#
# REGISTER_CAPABILITY: type=tool, id=run_code,
#   path=VM107/core/agents/invocation.py:run_code
# REGISTER_CAPABILITY: type=tool, id=run_build,
#   path=VM107/core/agents/invocation.py:run_build
# REGISTER_CAPABILITY: type=tool, id=run_backtest,
#   path=VM107/core/agents/invocation.py:run_backtest
# REGISTER_CAPABILITY: type=tool, id=run_critic,
#   path=VM107/core/agents/invocation.py:run_critic
# (Actual YAML files for these capabilities are deferred to Plan 09 registry
# consolidation — the orchestrator service YAML at Plan 02 lists them as
# related_capabilities.)
# ---------------------------------------------------------------------------


def _build_strategy_prompt_payload(
    hypothesis: Hypothesis,
    refinement_context: Optional[RefinementContextEnvelope],
) -> str:
    """Compose the Strategy Agent subordinate's input payload.

    Phase 44 sent ``hypothesis.model_dump_json()`` alone. Phase 48 folds an
    optional RefinementContextEnvelope into a small JSON wrapper so the
    Strategy Agent prompt template can read targets without prose injection.
    """
    if refinement_context is None:
        return hypothesis.model_dump_json()
    import json as _json
    return _json.dumps({
        "hypothesis": hypothesis.model_dump(mode="json"),
        "refinement_context": refinement_context.model_dump(mode="json"),
    })


def _build_code_prompt_payload(
    spec: StrategySpec,
    refinement_context: Optional[RefinementContextEnvelope],
) -> str:
    """Compose the Code Agent subordinate's input payload."""
    if refinement_context is None:
        return spec.model_dump_json()
    import json as _json
    return _json.dumps({
        "strategy_spec": spec.model_dump(mode="json"),
        "refinement_context": refinement_context.model_dump(mode="json"),
    })


def _build_critic_prompt_payload(
    state: RefinementLoopState,
    spec: StrategySpec,
    code: CodeModule,
    build: BuildReport,
    result: BacktestResult,
) -> str:
    """Compose the strategy_refinement_critic subordinate's input payload."""
    import json as _json
    return _json.dumps({
        "loop_state": state.model_dump(mode="json"),
        "strategy_spec": spec.model_dump(mode="json"),
        "code_module": code.model_dump(mode="json"),
        "build_report": build.model_dump(mode="json"),
        "backtest_result": result.model_dump(mode="json"),
    })


def _derived_confidence_ceiling(backtest_result: BacktestResult) -> float:
    """Phase 48 Plan 06 HYBRID confidence-clamp ceiling.

    CONTEXT § Decision 1 (planner Q7): the LLM Critic emits a raw confidence;
    the orchestrator (run_critic) clamps to a deterministic ceiling computed
    from backtest robustness signals so the Critic never claims more certainty
    than the underlying evidence supports.

    Formula:
        sample_size_ratio   = min(1.0, sample_size / 250)
        regime_coverage_ratio = backtest_result.metrics.regime_coverage
        derived_ceiling     = 0.5 + 0.3 * sample_size_ratio
                                  + 0.2 * regime_coverage_ratio

    Properties:
        - Minimum ceiling = 0.5 (a Critic can never claim less than coin-flip)
        - Maximum ceiling = 1.0 (perfect sample + perfect regime coverage)
        - Pure function: same inputs -> same output (no I/O, no globals).

    The Critic-budget-blind invariant (Plan 05) is unaffected — this helper
    reads BacktestResult, not RefinementLoopState.budget_snapshot.
    """
    sample_size_ratio = min(1.0, backtest_result.sample_size / 250.0)
    regime_coverage_ratio = backtest_result.metrics.regime_coverage
    return 0.5 + 0.3 * sample_size_ratio + 0.2 * regime_coverage_ratio


def _invoke_build_agent(module: CodeModule) -> BuildReport:
    """Deterministic Build Agent dispatch — pure-Python service path.

    Phase 45 / Phase 48 § Decision 14: build_agent is NOT an LLM agent profile.
    Late-imports build_agent.run() (when the module ships) to avoid circular
    deps. Until Plan 03+ ships the build pipeline, this returns a minimal
    success envelope so the typed-wrapper signature is testable.

    Test paths patch this function directly (see
    tests/core/agents/test_invocation_phase48_wrappers.py:test_run_build_*).
    """
    try:
        from core.agents import build_agent  # type: ignore[import]
    except ImportError:
        # Plan 03 hasn't shipped build_agent yet — return a deterministic
        # placeholder so the wrapper contract is stable. Plan 03 replaces
        # this path with a real compile + static-analysis dispatch.
        return BuildReport(
            status="success",
            artifact_id=None,
            errors=[],
            warnings=["build_agent module not yet shipped (Plan 03)"],
        )
    return build_agent.run(module)


def run_code(
    spec: StrategySpec,
    *,
    db: Any = None,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    refinement_context: Optional[RefinementContextEnvelope] = None,
) -> CodeModule:
    """Invoke Code Agent → CodeModule (typed).

    Phase 48 Plan 48-01 — closes Phase 45 deferral.

    Same retry-once-then-fail policy as run_idea / run_strategy. When
    ``refinement_context`` is provided (CODE_MODULE-scoped refinement), the
    Code Agent regenerates from the CURRENT StrategySpec plus the prior
    iteration's RefinementTargets. STRATEGY_SPEC-scoped refinements do NOT
    flow through this wrapper — the orchestrator regenerates Strategy first
    (CONTEXT § Decision 5).

    Args:
        spec: REQUIRED StrategySpec instance — Code Agent never auto-calls Strategy.
        db: MongoDB database handle. If None, envelope persistence is skipped.
        task_id: Phase 42 task identifier. Defaults to generated UUID.
        parent_task_id: Optional parent task.
        refinement_context: Optional Phase 48 RefinementContextEnvelope.

    Returns:
        CodeModule.

    Raises:
        InvalidInputError: spec is not a StrategySpec instance.
        CodeAgentDegradedError: Both attempts returned PlainTextResult.
    """
    from core.agents.envelope_writer import build_envelope, write_envelope

    if not isinstance(spec, StrategySpec):
        raise InvalidInputError(
            f"run_code requires a StrategySpec instance, got {type(spec).__name__}."
        )

    _task_id = task_id or f"api-{uuid.uuid4()}"
    sub_payload = _build_code_prompt_payload(spec, refinement_context)

    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            _sub_result = _call_subordinate_sync("code_agent", sub_payload)
        except RuntimeError as e:
            log.error("code_agent bootstrap/runtime failure: %s", e, exc_info=True)
            raise CodeAgentDegradedError(
                error_chain=[f"runtime_failure: {type(e).__name__}: {e}"]
            ) from e
        if isinstance(_sub_result, tuple):
            raw, telemetry = _sub_result
        else:
            raw, telemetry = _sub_result, {}
        result = safe_parse(raw, CodeModule)

        if isinstance(result, CodeModule):
            if db is not None:
                envelope = build_envelope(
                    task_id=_task_id,
                    parent_task_id=parent_task_id,
                    agent_id="code_agent",
                    input_payload={"strategy_spec_name": spec.name},
                    output_payload=result.model_dump(),
                    telemetry=telemetry,
                    status="success",
                    source_envelope_id=None,
                )
                write_envelope(db, envelope)
            return result

        assert isinstance(result, PlainTextResult)
        log.warning(
            "code_agent degraded on attempt %d/2 — error_chain=%s",
            attempt,
            result.error_chain,
        )
        if db is not None:
            envelope = build_envelope(
                task_id=_task_id,
                parent_task_id=parent_task_id,
                agent_id="code_agent",
                input_payload={"strategy_spec_name": spec.name},
                output_payload={
                    "plain_text": result.raw_output,
                    "error_chain": result.error_chain,
                },
                telemetry=telemetry,
                status="degraded",
                source_envelope_id=None,
            )
            write_envelope(db, envelope)

    raise CodeAgentDegradedError(
        error_chain=[f"attempt_{i + 1}_degraded" for i in range(2)]
    )


def run_build(module: CodeModule) -> BuildReport:
    """Invoke deterministic Build Agent → BuildReport.

    Phase 45 deferral closed here. Pure-Python service path — NO LLM call,
    NO retry. CONTEXT § Decision 14 + § code_context: build_agent is the
    reference architecture for orchestrator-style services.

    Args:
        module: CodeModule to build.

    Returns:
        BuildReport with status ∈ {"success", "failure"}.

    Raises:
        InvalidInputError: module is not a CodeModule instance.
    """
    if not isinstance(module, CodeModule):
        raise InvalidInputError(
            f"run_build requires a CodeModule instance, got {type(module).__name__}."
        )
    return _invoke_build_agent(module)


def run_backtest(
    module: CodeModule,
    *,
    db: Any = None,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> BacktestResult:
    """Invoke Backtester Agent → BacktestResult (typed).

    Phase 48 Plan 48-01 — closes Phase 45 deferral.

    Phase 45 / 48 plan note: Backtester invocation is mediated by an LLM-driven
    agent profile (translating CodeModule to a backtester job, parsing back
    metrics), so retry-once-then-fail applies on the LLM step. The underlying
    compute (VM102 backtester) is deterministic and tracked separately as
    ExecutionCost(category="INFRASTRUCTURE").

    Args:
        module: REQUIRED CodeModule instance.
        db: MongoDB database handle. Envelope persistence skipped if None.
        task_id: Phase 42 task identifier.
        parent_task_id: Optional parent task.

    Returns:
        BacktestResult.

    Raises:
        InvalidInputError: module is not a CodeModule instance.
        BacktesterDegradedError: Both attempts returned PlainTextResult.
    """
    from core.agents.envelope_writer import build_envelope, write_envelope

    if not isinstance(module, CodeModule):
        raise InvalidInputError(
            f"run_backtest requires a CodeModule instance, got {type(module).__name__}."
        )

    _task_id = task_id or f"api-{uuid.uuid4()}"
    sub_payload = module.model_dump_json()

    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            _sub_result = _call_subordinate_sync("backtester_agent", sub_payload)
        except RuntimeError as e:
            log.error("backtester_agent bootstrap/runtime failure: %s", e, exc_info=True)
            raise BacktesterDegradedError(
                error_chain=[f"runtime_failure: {type(e).__name__}: {e}"]
            ) from e
        if isinstance(_sub_result, tuple):
            raw, telemetry = _sub_result
        else:
            raw, telemetry = _sub_result, {}
        result = safe_parse(raw, BacktestResult)

        if isinstance(result, BacktestResult):
            if db is not None:
                envelope = build_envelope(
                    task_id=_task_id,
                    parent_task_id=parent_task_id,
                    agent_id="backtester_agent",
                    input_payload={"code_module_version": module.version},
                    output_payload=result.model_dump(),
                    telemetry=telemetry,
                    status="success",
                    source_envelope_id=None,
                )
                write_envelope(db, envelope)
            return result

        assert isinstance(result, PlainTextResult)
        log.warning(
            "backtester_agent degraded on attempt %d/2 — error_chain=%s",
            attempt,
            result.error_chain,
        )
        if db is not None:
            envelope = build_envelope(
                task_id=_task_id,
                parent_task_id=parent_task_id,
                agent_id="backtester_agent",
                input_payload={"code_module_version": module.version},
                output_payload={
                    "plain_text": result.raw_output,
                    "error_chain": result.error_chain,
                },
                telemetry=telemetry,
                status="degraded",
                source_envelope_id=None,
            )
            write_envelope(db, envelope)

    raise BacktesterDegradedError(
        error_chain=[f"attempt_{i + 1}_degraded" for i in range(2)]
    )


def run_critic(
    state: RefinementLoopState,
    spec: StrategySpec,
    code: CodeModule,
    build: BuildReport,
    result: BacktestResult,
    *,
    db: Any = None,
    task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> CriticVerdict:
    """Invoke strategy_refinement_critic → CriticVerdict (typed).

    Phase 48 Plan 48-01 — new Phase 48 wrapper. Uses model-routing affinity
    entry ``strategy_refinement_critic`` (Plan 06 adds the YAML routing entry).

    safe_parse(CriticVerdict) + retry-once-then-fail. Second failure raises
    CriticDegradedError — the orchestrator maps to
    TerminationReason.CRITIC_DEGRADED for replay-archaeology granularity
    (CONTEXT § Decision 4).

    Args:
        state: Current RefinementLoopState.
        spec: Current StrategySpec (latest iteration).
        code: Current CodeModule.
        build: Latest BuildReport.
        result: Latest BacktestResult.
        db: MongoDB database handle. Envelope persistence skipped if None.
        task_id: Phase 42 task identifier.
        parent_task_id: Optional parent task.

    Returns:
        CriticVerdict (verdict ∈ {ACCEPT, REFINE, REJECT}).

    Raises:
        InvalidInputError: any input is the wrong type.
        CriticDegradedError: Both attempts returned PlainTextResult.
    """
    from core.agents.envelope_writer import build_envelope, write_envelope

    if not isinstance(state, RefinementLoopState):
        raise InvalidInputError(
            f"run_critic requires a RefinementLoopState, got {type(state).__name__}."
        )
    if not isinstance(spec, StrategySpec):
        raise InvalidInputError(
            f"run_critic requires a StrategySpec, got {type(spec).__name__}."
        )
    if not isinstance(code, CodeModule):
        raise InvalidInputError(
            f"run_critic requires a CodeModule, got {type(code).__name__}."
        )
    if not isinstance(build, BuildReport):
        raise InvalidInputError(
            f"run_critic requires a BuildReport, got {type(build).__name__}."
        )
    if not isinstance(result, BacktestResult):
        raise InvalidInputError(
            f"run_critic requires a BacktestResult, got {type(result).__name__}."
        )

    _task_id = task_id or f"api-{uuid.uuid4()}"
    sub_payload = _build_critic_prompt_payload(state, spec, code, build, result)

    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            _sub_result = _call_subordinate_sync(
                "strategy_refinement_critic", sub_payload
            )
        except RuntimeError as e:
            log.error("strategy_refinement_critic bootstrap/runtime failure: %s", e, exc_info=True)
            raise CriticDegradedError(
                error_chain=[f"runtime_failure: {type(e).__name__}: {e}"]
            ) from e
        if isinstance(_sub_result, tuple):
            raw, telemetry = _sub_result
        else:
            raw, telemetry = _sub_result, {}
        verdict = safe_parse(raw, CriticVerdict)

        if isinstance(verdict, CriticVerdict):
            # Phase 48 Plan 06 HYBRID confidence clamp (CONTEXT § Decision 1):
            # the LLM emits a raw confidence; we clamp to the deterministic
            # derived_ceiling so the Critic never overstates certainty given
            # the backtest's robustness signals. Both raw + clamped values
            # persist via the envelope output_payload so replay archaeology
            # can recover the original LLM emission.
            raw_confidence = verdict.confidence
            derived_ceiling = _derived_confidence_ceiling(result)
            clamped = min(raw_confidence, derived_ceiling)
            if clamped != raw_confidence:
                verdict = verdict.model_copy(update={"confidence": clamped})

            if db is not None:
                output_payload = verdict.model_dump()
                output_payload["raw_confidence"] = raw_confidence
                output_payload["derived_confidence_ceiling"] = derived_ceiling
                envelope = build_envelope(
                    task_id=_task_id,
                    parent_task_id=parent_task_id,
                    agent_id="strategy_refinement_critic",
                    input_payload={"loop_id": state.loop_id, "iteration": state.iteration},
                    output_payload=output_payload,
                    telemetry=telemetry,
                    status="success",
                    source_envelope_id=None,
                )
                write_envelope(db, envelope)
            return verdict

        assert isinstance(verdict, PlainTextResult)
        log.warning(
            "strategy_refinement_critic degraded on attempt %d/2 — error_chain=%s",
            attempt,
            verdict.error_chain,
        )
        if db is not None:
            envelope = build_envelope(
                task_id=_task_id,
                parent_task_id=parent_task_id,
                agent_id="strategy_refinement_critic",
                input_payload={"loop_id": state.loop_id, "iteration": state.iteration},
                output_payload={
                    "plain_text": verdict.raw_output,
                    "error_chain": verdict.error_chain,
                },
                telemetry=telemetry,
                status="degraded",
                source_envelope_id=None,
            )
            write_envelope(db, envelope)

    raise CriticDegradedError(
        error_chain=[f"attempt_{i + 1}_degraded" for i in range(2)]
    )
