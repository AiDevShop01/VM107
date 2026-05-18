"""Phase 44 invocation-layer exceptions.

Raised by core.agents.invocation when typed wrappers detect degraded or
invalid-input conditions. Separate module to avoid circular imports.
"""
from __future__ import annotations


class InvalidInputError(TypeError):
    """Raised when run_strategy receives a non-Hypothesis input.

    Per CONTEXT.md § Strategy Agent:
        'assert isinstance(input, Hypothesis). Reject anything else with
         InvalidInputError — NO auto-wrapping/auto-calling Idea Agent.'
    """
    pass


class _AgentDegradedError(RuntimeError):
    """Base — raised when safe_parse returns PlainTextResult on retry too.

    Both initial attempt and the single allowed retry produced unstructured
    output. Fail fast — do NOT pass PlainTextResult downstream.
    """

    def __init__(self, agent_id: str, error_chain: list[str]) -> None:
        self.agent_id = agent_id
        self.error_chain = error_chain
        super().__init__(
            f"Agent '{agent_id}' produced unstructured output on initial call AND retry. "
            f"error_chain={error_chain}"
        )


class IdeaAgentDegradedError(_AgentDegradedError):
    """Raised when Idea Agent degrades on both initial call and retry."""

    def __init__(self, error_chain: list[str] | None = None) -> None:
        super().__init__("idea_agent", error_chain or [])


class StrategyAgentDegradedError(_AgentDegradedError):
    """Raised when Strategy Agent degrades on both initial call and retry."""

    def __init__(self, error_chain: list[str] | None = None) -> None:
        super().__init__("strategy_agent", error_chain or [])


# Phase 48 Plan 48-01 — typed degraded exceptions for the new wrappers.
# Same retry-once-then-fail discipline as IdeaAgentDegradedError /
# StrategyAgentDegradedError. Orchestrator catches these and maps to
# TerminationReason.STRATEGY_DEGRADED / CODE_DEGRADED / BACKTEST_DEGRADED /
# CRITIC_DEGRADED for replay-archaeology granularity (CONTEXT § Decision 4).


class CodeAgentDegradedError(_AgentDegradedError):
    """Raised when Code Agent returns PlainTextResult on both initial call + retry."""

    def __init__(self, error_chain: list[str] | None = None) -> None:
        super().__init__("code_agent", error_chain or [])


class BacktesterDegradedError(_AgentDegradedError):
    """Raised when Backtester Agent returns PlainTextResult on both initial call + retry."""

    def __init__(self, error_chain: list[str] | None = None) -> None:
        super().__init__("backtester_agent", error_chain or [])


class CriticDegradedError(_AgentDegradedError):
    """Raised when strategy_refinement_critic returns PlainTextResult on both attempts.

    Orchestrator maps this to TerminationReason.CRITIC_DEGRADED (the
    BUILD_FAILURE sub-state for replay archaeology).
    """

    def __init__(self, error_chain: list[str] | None = None) -> None:
        super().__init__("strategy_refinement_critic", error_chain or [])


class EvaluationContractViolation(_AgentDegradedError):
    """Raised when the evaluation runner degrades on both initial call and retry.

    Both attempts returned PlainTextResult from safe_parse. VM107 ApiHandler
    catches this and returns 502 with structured error body. No Postgres row
    created. Failure envelope IS persisted before the raise.

    The runner sets `envelope_id` after writing the failure envelope so the
    ApiHandler can echo it in the 502 response (per CONTEXT-fail-fast lock).
    """

    def __init__(
        self,
        error_chain: list[str] | None = None,
        envelope_id: str | None = None,
    ) -> None:
        super().__init__("evaluation_runner", error_chain or [])
        self.envelope_id: str | None = envelope_id
