"""OvernightDeltaContract — Phase 67 Plan 06.

Pydantic v2 frozen + extra=forbid contract produced by OvernightDeltaEmitter.
Carries exactly FOUR bucket deltas in fixed order:
    FX → BONDS → COMMODITIES → CRYPTO

Plan 09 PRE state overnight namespace consumes via VM107OvernightDeltaClient.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_BUCKET_ORDER: tuple[str, ...] = ("FX", "BONDS", "COMMODITIES", "CRYPTO")


class BucketDelta(BaseModel):
    """Single bucket overnight delta — one row in the 4-row OvernightDelta."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    bucket: Literal["FX", "BONDS", "COMMODITIES", "CRYPTO"]
    headline: str  # 1-line summary of overnight move
    notable_symbols: list[str] = Field(default_factory=list)  # 0-3 tickers
    direction: Literal["up", "down", "mixed", "flat"]
    magnitude_label: Literal["small", "moderate", "large", "extreme"]
    confidence: float
    demo: bool = Field(default=False, alias="_demo")


class OvernightDeltaContract(BaseModel):
    """Overnight delta contract — fixed 4-bucket envelope.

    Fixed bucket order locked at validator level so consumers can index by
    position rather than search by name (UX rendering benefits + Phase 09 lock).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    delta_id: str
    account_id: int
    generated_at: datetime

    buckets: list[BucketDelta]  # exactly 4 items in fixed order

    overall_summary: str
    llm_enriched_summary: str | None = None

    confidence_score: float
    confidence_tier: Literal["FULL", "PARTIAL", "DEGRADED"]
    missing_sources: list[str] = Field(default_factory=list)
    demo: bool = Field(default=False, alias="_demo")

    @model_validator(mode="after")
    def _validate_bucket_order_and_count(self) -> "OvernightDeltaContract":
        if len(self.buckets) != 4:
            raise ValueError(
                f"OvernightDeltaContract requires exactly 4 buckets; got {len(self.buckets)}"
            )
        actual_order = tuple(b.bucket for b in self.buckets)
        if actual_order != _BUCKET_ORDER:
            raise ValueError(
                "OvernightDeltaContract bucket order must be "
                f"{_BUCKET_ORDER}; got {actual_order}"
            )
        return self
