"""Phase 48 Plan 48-01 — REQ-48-D14. ExecutionCost schema with LLM/INFRASTRUCTURE category."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import ExecutionCost


def test_execution_cost_llm_round_trip() -> None:
    cost = ExecutionCost(
        tokens_in=1024,
        tokens_out=512,
        usd_cost=0.0123,
        wall_time_ms=875,
        category="LLM",
    )
    rehydrated = ExecutionCost.model_validate(cost.model_dump())
    assert rehydrated.tokens_in == 1024
    assert rehydrated.tokens_out == 512
    assert rehydrated.usd_cost == pytest.approx(0.0123)
    assert rehydrated.wall_time_ms == 875
    assert rehydrated.category == "LLM"


def test_execution_cost_infrastructure_category() -> None:
    cost = ExecutionCost(
        tokens_in=0,
        tokens_out=0,
        usd_cost=0.0,
        wall_time_ms=120_000,
        category="INFRASTRUCTURE",
    )
    assert cost.category == "INFRASTRUCTURE"


def test_execution_cost_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        ExecutionCost(
            tokens_in=0,
            tokens_out=0,
            usd_cost=0.0,
            wall_time_ms=10,
            category="DATABASE",  # type: ignore[arg-type]
        )


def test_execution_cost_rejects_negative_tokens() -> None:
    """tokens_in / tokens_out must be non-negative."""
    with pytest.raises(ValidationError):
        ExecutionCost(
            tokens_in=-1,
            tokens_out=0,
            usd_cost=0.0,
            wall_time_ms=10,
            category="LLM",
        )
