"""Phase 48 Plan 48-01 — REQ-48-D4. TerminationReason enum: 14 members (9 base + 5 BUILD_FAILURE sub-states).

Planner Discretion (CONTEXT.md § Decision 4 / Claude's Discretion):
  Splits BUILD_FAILURE into 5 sub-states (CRITIC_DEGRADED, STRATEGY_DEGRADED, CODE_DEGRADED,
  BUILD_FAILED, BACKTEST_DEGRADED) for replay-archaeology granularity. The bucket
  BUILD_FAILURE remains as a top-level state for orchestrator-level fall-through;
  the 5 sub-states are emitted by pipeline-stage degradation paths.
"""
import pytest

from core.contracts.schemas import TerminationReason


def test_termination_reason_has_fourteen_members() -> None:
    """REQ-48-D4: 14 members total."""
    assert len(list(TerminationReason)) == 14


def test_termination_reason_nine_base_states() -> None:
    """9 base CONTEXT.md § Decision 4 states present."""
    names = {m.name for m in TerminationReason}
    for required in (
        "ACCEPTED",
        "CRITIC_REJECT",
        "HARD_VETO",
        "IDENTITY_DRIFT",
        "CONVERGENCE_STALL",
        "BUDGET_EXCEEDED_ITERATION",
        "BUDGET_EXCEEDED_LOOP",
        "MAX_ITERATIONS",
        "BUILD_FAILURE",
    ):
        assert required in names, f"missing required base state: {required}"


def test_termination_reason_five_build_failure_substates() -> None:
    """5 BUILD_FAILURE sub-states present (planner discretion: replay-archaeology granularity)."""
    names = {m.name for m in TerminationReason}
    for required in (
        "CRITIC_DEGRADED",
        "STRATEGY_DEGRADED",
        "CODE_DEGRADED",
        "BUILD_FAILED",
        "BACKTEST_DEGRADED",
    ):
        assert required in names, f"missing BUILD_FAILURE sub-state: {required}"


def test_termination_reason_values_are_string_enum() -> None:
    """StrEnum semantics — every member's value is a string equal to its name."""
    for m in TerminationReason:
        assert isinstance(m.value, str)
        assert m.value == m.name
