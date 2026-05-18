"""Phase 48 Plan 48-01 — REQ-48-D4. RefinementOutcome schema."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import (
    ExecutionCost,
    RefinementOutcome,
    TerminationReason,
)


def _cost() -> ExecutionCost:
    return ExecutionCost(
        tokens_in=100,
        tokens_out=200,
        usd_cost=0.05,
        wall_time_ms=1000,
        category="LLM",
    )


def test_refinement_outcome_accepted_path() -> None:
    """ACCEPTED → accepted_strategy_id set, rejected_strategy_id None."""
    outcome = RefinementOutcome(
        loop_id="loop_001",
        termination_reason=TerminationReason.ACCEPTED,
        accepted_strategy_id="acc_001",
        rejected_strategy_id=None,
        final_iteration=2,
        total_cost=_cost(),
    )
    rehydrated = RefinementOutcome.model_validate(outcome.model_dump())
    assert rehydrated.termination_reason == TerminationReason.ACCEPTED
    assert rehydrated.accepted_strategy_id == "acc_001"
    assert rehydrated.rejected_strategy_id is None
    assert rehydrated.final_iteration == 2


def test_refinement_outcome_rejected_path() -> None:
    """CRITIC_REJECT → rejected_strategy_id set, accepted_strategy_id None."""
    outcome = RefinementOutcome(
        loop_id="loop_002",
        termination_reason=TerminationReason.CRITIC_REJECT,
        accepted_strategy_id=None,
        rejected_strategy_id="rej_001",
        final_iteration=3,
        total_cost=_cost(),
    )
    assert outcome.accepted_strategy_id is None
    assert outcome.rejected_strategy_id == "rej_001"


def test_refinement_outcome_rejects_unknown_termination_reason() -> None:
    """Termination reason must be a valid TerminationReason enum value."""
    with pytest.raises(ValidationError):
        RefinementOutcome(
            loop_id="loop",
            termination_reason="NOT_A_REASON",  # type: ignore[arg-type]
            accepted_strategy_id=None,
            rejected_strategy_id=None,
            final_iteration=0,
            total_cost=_cost(),
        )
