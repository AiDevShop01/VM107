"""Phase 48 Plan 48-01 — REQ-48-EXCEPTIONS. 6 new typed exception classes."""
import pytest

from core.contracts.exceptions import (
    BudgetExceededError,
    ConvergenceStallError,
    IdentityDriftError,
    LoopBudgetExceeded,
    OrphanStrategyError,
    RefinementRoutingError,
    SchemaVersionMismatchError,
)


def test_refinement_routing_error_is_value_error_subclass() -> None:
    assert issubclass(RefinementRoutingError, ValueError)
    err = RefinementRoutingError("bad scope combination")
    assert isinstance(err, ValueError)
    assert "bad scope combination" in str(err)


def test_identity_drift_error_is_runtime_error_subclass() -> None:
    assert issubclass(IdentityDriftError, RuntimeError)


def test_identity_drift_error_carries_iteration_score_threshold() -> None:
    err = IdentityDriftError(iteration=2, score=0.65, threshold=0.80)
    assert err.iteration == 2
    assert err.score == pytest.approx(0.65)
    assert err.threshold == pytest.approx(0.80)
    msg = str(err)
    assert "iteration 2" in msg
    assert "0.650" in msg
    assert "0.800" in msg


def test_convergence_stall_error_is_runtime_error_subclass() -> None:
    assert issubclass(ConvergenceStallError, RuntimeError)
    err = ConvergenceStallError("repeated target tuple")
    assert isinstance(err, RuntimeError)


def test_budget_exceeded_error_is_runtime_error_subclass() -> None:
    """CONTEXT § Decision 14: distinct from Phase 38's BoundaryStatus.*_EXCEEDED."""
    assert issubclass(BudgetExceededError, RuntimeError)
    # Must NOT be a subclass of Phase 38 boundary error (it's a separate hierarchy).
    err = BudgetExceededError("loop cap hit")
    assert isinstance(err, RuntimeError)


def test_orphan_strategy_error_is_value_error_subclass() -> None:
    assert issubclass(OrphanStrategyError, ValueError)
    err = OrphanStrategyError("StrategySpec lacks root_hypothesis_id")
    assert isinstance(err, ValueError)


def test_loop_budget_exceeded_carries_scope_and_amounts() -> None:
    """CONTEXT § Decision 14: scope ∈ {ITERATION, LOOP} + consumed_usd + cap_usd."""
    err = LoopBudgetExceeded(scope="ITERATION", consumed_usd=1.25, cap_usd=1.00)
    assert err.scope == "ITERATION"
    assert err.consumed_usd == pytest.approx(1.25)
    assert err.cap_usd == pytest.approx(1.00)
    assert isinstance(err, RuntimeError)
    msg = str(err)
    assert "ITERATION" in msg
    assert "1.0000" in msg or "1.00" in msg


def test_loop_budget_exceeded_loop_scope() -> None:
    err = LoopBudgetExceeded(scope="LOOP", consumed_usd=10.5, cap_usd=10.0)
    assert err.scope == "LOOP"


def test_schema_version_mismatch_error_still_works() -> None:
    """Phase 44 SchemaVersionMismatchError must remain intact."""
    err = SchemaVersionMismatchError(expected=1, received=2)
    assert err.expected == 1
    assert err.received == 2
    assert isinstance(err, ValueError)
