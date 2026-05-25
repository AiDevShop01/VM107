"""ReflectionPromptContract — Phase 67 Plan 07 (REQ-67-4).

Pydantic v2 frozen + extra=forbid typed contract produced by
ReflectionPromptEmitter (VM107) and consumed by VM100 via
VM107ReflectionPromptClient (Plan 10 CLOSE journal_prompts namespace
+ Plan 12 MCP tool).

Architecture:
  * Deterministic-first — `base_prompt` is ALWAYS populated; LLM
    enrichment (`llm_enriched_prompt`) is additive and may be None.
  * REJECTED candidates persisted alongside selected ones (Phase 62
    tuning gold) with `selected=False` + `rejection_reason` +
    optional `rejected_by_diversity_guard`.
  * evidence_chain[] is a structured list of {kind, ref, weight}
    items — per RESEARCH recommendation, NOT a free-form string.

LOCKED prompt taxonomy (10 categories — load-bearing):
    DISCIPLINE / EXECUTION / REGIME / EMOTIONAL / LOCATION /
    PATIENCE / OVERTRADING / RISK / READINESS / EDGE_QUALITY

LOCKED intervention types (5):
    reflective / tactical / pattern-recognition / emotional / future-oriented

LOCKED intervention strengths (4):
    LOW / MODERATE / HIGH / CRITICAL
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Discriminated evidence kinds (RESEARCH recommendation — per-source weight,
# never a free-form string).
EvidenceKind = Literal[
    "discipline_flag",
    "cross_trade_pattern",
    "regime",
    "behavioral_evolution",
    "execution_trace",
    "readiness",
    "mentor_narrative",
]


PromptCategory = Literal[
    "DISCIPLINE",
    "EXECUTION",
    "REGIME",
    "EMOTIONAL",
    "LOCATION",
    "PATIENCE",
    "OVERTRADING",
    "RISK",
    "READINESS",
    "EDGE_QUALITY",
]


InterventionStrength = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
InterventionType = Literal[
    "reflective", "tactical", "pattern-recognition", "emotional", "future-oriented"
]


class EvidenceChainItem(BaseModel):
    """One structured evidence item with origin + weight.

    Weight is in [0.0, 1.0] reflecting how much this evidence contributed
    to the candidate's composite score.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    ref: str  # e.g. "discipline_flag:premature_entry" or "cross_trade_pattern:premature_entry_cluster"
    weight: float = Field(ge=0.0, le=1.0)


class ReflectionPromptContract(BaseModel):
    """One reflection prompt — selected OR rejected.

    Both selected (4 per set) and rejected (variable count) candidates
    use this contract. The `selected` boolean disambiguates; rejected
    candidates carry `rejection_reason` (always) and optionally
    `rejected_by_diversity_guard` (when a diversity rule fired).

    Per CONTEXT.md §4: both `base_prompt` AND `llm_enriched_prompt` are
    persisted so Phase 62 tuning can compare deterministic vs enriched
    surface across long horizons.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str
    account_id: int
    category: PromptCategory
    intervention_strength: InterventionStrength
    intervention_type: InterventionType

    base_prompt: str  # deterministic — ALWAYS populated
    llm_enriched_prompt: str | None = None  # additive — populated when novelty crossed
    selection_reason: str  # e.g. "discipline_repeat", "premature_entry_cluster"

    novelty_score: float
    behavioral_confidence_score: float
    confidence_score: float  # composite score from synthesizer
    emotional_load: float = Field(ge=0.0, le=1.0)

    originating_patterns: list[str] = Field(default_factory=list)
    originating_flags: list[str] = Field(default_factory=list)
    evidence_chain: list[EvidenceChainItem] = Field(default_factory=list)

    prompt_version: str  # deterministic library version, e.g. "v1.0.0"
    generated_at: datetime

    # Selection state — selected=False rows persisted for Phase 62 tuning gold.
    selected: bool = True
    rejection_reason: str | None = None
    rejected_by_diversity_guard: str | None = None


class ReflectionPromptSetContract(BaseModel):
    """4-prompt SET output from ReflectionPromptEmitter.

    `selected_prompts` is at most 4 (may be fewer when eligibility/coherence
    cannot fill the slot). `rejected_candidates` carries every candidate
    that was generated but not selected — Phase 62 tuning input.

    `reflection_set_coherence_score` reflects how clean the final set is
    (1.0 = no remediation; lower = swaps were needed or violations remain).
    `dominant_session_theme` carries the locked taxonomy category name
    when one domain genuinely dominated the candidate pool, else None.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    set_id: str
    account_id: int
    generated_at: datetime
    selected_prompts: list[ReflectionPromptContract] = Field(default_factory=list)
    rejected_candidates: list[ReflectionPromptContract] = Field(default_factory=list)
    reflection_set_coherence_score: float = Field(ge=0.0, le=1.0)
    dominant_session_theme: str | None = None
