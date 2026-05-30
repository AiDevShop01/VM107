"""Phase 73 — Pydantic schema for ``strategy_scoring_weights`` registry entries.

Every strategy ranked by the Phase 73 OpportunityRanker must have a
``VM107/registry/strategy_scoring_weights/<strategy_id>.yaml`` baseline that
declares the 9-category weights and their version. The 9 keys MUST match
``mission_control.contracts.score_snapshot.CATEGORIES`` and the values MUST
sum to exactly 100.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# Phase 73 canonical 9-category set (single source of truth lives in
# mission_control.contracts.score_snapshot.CATEGORIES; this module mirrors
# the names but enforces the count + sum invariant via validator).
EXPECTED_CATEGORIES = {
    "session_fit",
    "macro_fit",
    "structure_quality",
    "liquidity_context",
    "volatility_regime",
    "strategy_adherence",
    "risk_reward",
    "historical_analogue_strength",
    "behavioral_edge",
}


class StrategyScoringWeightsSpec(BaseModel):
    """Capability registry entry for a strategy's 9-category scoring weights."""

    id: str
    type: Literal["strategy_scoring_weights"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str

    strategy_id: str
    weights_version: int = Field(ge=0)
    weights: dict[str, int]  # 9 keys, values sum to 100
    description: str

    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False

    @model_validator(mode="after")
    def _validate_weights(self) -> "StrategyScoringWeightsSpec":
        if set(self.weights.keys()) != EXPECTED_CATEGORIES:
            missing = EXPECTED_CATEGORIES - set(self.weights.keys())
            extra = set(self.weights.keys()) - EXPECTED_CATEGORIES
            raise ValueError(
                f"weights keys must match the 9 canonical categories. "
                f"missing={missing!r} extra={extra!r}"
            )
        total = sum(int(v) for v in self.weights.values())
        if total != 100:
            raise ValueError(
                f"weights must sum to 100 (got {total})"
            )
        return self
