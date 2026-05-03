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
