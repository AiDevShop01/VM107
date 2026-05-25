"""MorningBriefContract — Phase 67 Plan 06.

Pydantic v2 frozen + extra=forbid typed contract produced by MorningBriefEmitter
(VM107) and consumed by VM100 via VM107MorningBriefClient.

Wire surface for the Mission Control PRE state center briefing namespace
(Plan 09 consumer). Carries:
  * Deterministic base (headline + body + top_catalysts + risk_alerts) — ALWAYS populated
  * Optional LLM-enriched additive overlay (additive only, never replaces base)
  * Confidence vector + 4-tier degradation classification
  * Phase 66 novelty score + threshold-crossed flag
  * _demo flip when degraded
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MorningBriefContract(BaseModel):
    """Typed contract for the morning briefing emitter output.

    Plan 09 PRE state briefing namespace consumes this via VM100MorningBriefClient.
    Frozen + extra=forbid — shape stability for downstream UI binding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    brief_id: str
    account_id: int
    generated_at: datetime

    # Deterministic base (ALWAYS populated regardless of novelty)
    headline: str
    body: str
    top_catalysts: list[str] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)

    # LLM enrichment (additive — None when novelty threshold not crossed)
    llm_enriched_headline: str | None = None
    llm_enriched_body: str | None = None

    # Confidence + degradation
    confidence_score: float
    confidence_tier: Literal["FULL", "PARTIAL", "DEGRADED"]
    missing_sources: list[str] = Field(default_factory=list)
    demo: bool = Field(default=False, alias="_demo")

    # Phase 66 novelty (shared NoveltyEngine instance)
    novelty_score: float
    novelty_crossed: bool
