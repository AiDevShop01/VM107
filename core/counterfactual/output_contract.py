"""Phase 89 Wave 2 — CounterfactualOutput Pydantic contract.

Per 89-ARCHITECTURE §5.3:
  - CounterfactualOutput: full result with expected-move table per asset per window
  - ExpectedMove: mean_pct, confidence_interval, sample_size, low_confidence_flag
  - InsufficientAnaloguesResponse: emitted when n < k_analogues_minimum (Decision 2)
  - BlockingContradictionRefusal: emitted when active_blocking contradition found (Decision 7)
  - CounterfactualResponse: union type for all engine outcomes

Per project locks:
  - No hardcoded values; env-driven config enforced in forecast_client
  - Pydantic v2 models; strict validation (fail-fast on bad data)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─── CitationRef (Phase 71 contract) ─────────────────────────────────────────

class CitationRef(BaseModel):
    """Phase 71 evidence drawer citation reference."""

    ref_id: str
    source_type: Literal["release", "event-study", "belief", "analogue", "tool_result"]
    label: str | None = None
    url: str | None = None


# ─── ExpectedMove ────────────────────────────────────────────────────────────

class ExpectedMove(BaseModel):
    """Expected asset move at a given window (T+1h / T+1d / T+1w).

    Per 89-ARCHITECTURE §5.3.

    Attributes:
        mean_pct: Mean percentage move across analogues.
        confidence_interval: 95% CI as (low, high) tuple.
        sample_size: Number of analogues contributing to this cell (>=0).
        low_confidence_flag: True if n<10, period>20y stale, OR regime divergent.
    """

    mean_pct: float
    confidence_interval: tuple[float, float]
    sample_size: Annotated[int, Field(ge=0)]  # must be >= 0
    low_confidence_flag: bool

    @field_validator("sample_size")
    @classmethod
    def sample_size_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"sample_size must be >= 0, got {v}")
        return v


# ─── CounterfactualOutput ────────────────────────────────────────────────────

class CounterfactualOutput(BaseModel):
    """Full counterfactual simulation result.

    Per 89-ARCHITECTURE §5.3 CounterfactualOutput contract.

    query_id: Unique identifier for this counterfactual run.
    indicator: FRED indicator ID (e.g. "CPIAUCSL").
    hypothetical_value: The "what if" value supplied by the user.
    baseline_value: Latest actual print (nullable if unknown).
    analogue_period: (start_date, end_date) span of the analogue set.
    analogue_count: How many analogues contributed to the expected-move table.
    expected_moves: {asset: {window: ExpectedMove}} for 4 assets × 3 windows.
    narrative: Short prose summary (within word_cap per agent profile).
    regime_alignment: "aligned" / "partial" / "divergent" per Phase 87 regime.
    citations: Phase 71 evidence references.
    forecast_source: Which path generated the expected_moves
        ("phase_86_event_study_fallback" or "phase_90_layer_4").
    """

    query_id: UUID
    indicator: str
    hypothetical_value: float
    baseline_value: float | None = None
    analogue_period: tuple[date, date]
    analogue_count: int
    expected_moves: dict[
        Literal["DXY", "Gold", "SPX", "UST10Y"],
        dict[Literal["T+1h", "T+1d", "T+1w"], ExpectedMove],
    ]
    narrative: str = ""
    regime_alignment: Literal["aligned", "partial", "divergent"] = "partial"
    citations: list[CitationRef] = Field(default_factory=list)
    forecast_source: str = "phase_86_event_study_fallback"


# ─── InsufficientAnaloguesResponse (Decision 2) ─────────────────────────────

class InsufficientAnaloguesResponse(BaseModel):
    """Emitted when analogue count < k_analogues_minimum (5 per Decision 2).

    Engine MUST NOT fabricate expected_moves. This response type has no
    expected_moves field by design — if a caller tries to access it they get
    an AttributeError immediately.

    Attributes:
        status: Always "insufficient_analogues".
        sample_size: How many analogues were actually found.
        message: Human-readable refusal message including N.
        hypothetical_value: Echo of the user's requested hypothetical.
    """

    status: Literal["insufficient_analogues"]
    sample_size: int
    message: str
    hypothetical_value: float


# ─── BlockingContradictionRefusal (Decision 7) ──────────────────────────────

class BlockingContradictionRefusal(BaseModel):
    """Emitted when active_blocking contradiction found for the indicator.

    Per Decision 7: counterfactual checks belief_store.active_blocking() before emit.
    If any blocking contradiction is active, engine refuses — does NOT fabricate.

    Attributes:
        status: Always "blocked".
        reason: Human-readable explanation of the block.
        cta: Call-to-action for the user ("Open Contradiction Inbox").
        contradiction_id: ID of the first blocking contradiction (nullable).
    """

    status: Literal["blocked"]
    reason: str
    cta: str
    contradiction_id: str | None = None


# ─── ForecastUnavailableResponse (Pitfall 5) ─────────────────────────────────

class ForecastUnavailableResponse(BaseModel):
    """Emitted when BOTH Phase 90 and Phase 86 fallback are unavailable.

    Per Pitfall 5: never silently return fake numbers. When both paths fail,
    the engine raises ForecastUnavailable; the caller converts it to this
    response. NEVER includes expected_moves (no fabrication).
    """

    status: Literal["forecast_unavailable", "degraded"]
    reason: str
    indicator: str
    hypothetical_value: float


# ─── Union type ───────────────────────────────────────────────────────────────

CounterfactualResponse = (
    CounterfactualOutput
    | InsufficientAnaloguesResponse
    | BlockingContradictionRefusal
    | ForecastUnavailableResponse
)
