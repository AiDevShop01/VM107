"""Phase 67 Plan 07 — Diversity guards + coherence pass tests (Task 2).

Diversity guards (CONTEXT.md §4 — default rules):
    - max 2 prompts per same category
    - max 1 prompt per same intervention_type
    - max 1 prompt per same originating_pattern

Dominant-session-theme override (CONTEXT.md §4):
    - allow max 3 per category
    - allow max 2 per intervention_type

Coherence pass on 4-prompt SET:
    - No contradictions (e.g. "too aggressive" + "too passive")
    - emotional_load budget: sum ≤ 2.5
    - Mix temporal scales: at least 1 immediate + at least 1 longitudinal
    - reflection_set_coherence_score in [0.0, 1.0]
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from emitters.reflection.coherence import (
    CONTRADICTION_PAIRS,
    coherence_check,
)
from emitters.reflection.diversity_guards import apply_diversity_guards


pytestmark = pytest.mark.phase_67


# ── Test candidate dataclass (local mirror of synthesizer.Candidate) ───────


@dataclass(frozen=False)
class _C:
    """Plain mutable candidate for guard tests — synthesizer.Candidate
    mirror with minimum fields needed by the guard functions."""

    candidate_id: str
    category: str
    intervention_type: str
    intervention_strength: str = "MODERATE"
    originating_pattern: str = ""
    emotional_load: float = 0.5
    temporal_scale: str = "immediate-session"  # immediate-session | longitudinal
    score: float = 0.5
    base_prompt: str = "Sample prompt text"
    rejected_by_diversity_guard: str | None = None
    selected: bool = True
    flags: tuple[str, ...] = field(default_factory=tuple)


# ── 1. Diversity guard — default rules ─────────────────────────────────────


def test_diversity_max_2_per_category_default():
    """Default: max 2 prompts per category."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.9),
        _C("c2", "DISCIPLINE", "tactical", originating_pattern="p2", score=0.85),
        _C("c3", "DISCIPLINE", "emotional", originating_pattern="p3", score=0.80),
        _C("c4", "EXECUTION", "future-oriented", originating_pattern="p4", score=0.75),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme=None)
    discipline_count = sum(1 for s in selected if s.category == "DISCIPLINE")
    assert discipline_count <= 2
    # The 3rd DISCIPLINE candidate should be in rejected with a reason
    rejected_disc = [r for r in rejected if r.category == "DISCIPLINE"]
    assert len(rejected_disc) >= 1
    assert rejected_disc[0].rejected_by_diversity_guard


def test_diversity_max_1_per_intervention_type_default():
    """Default: max 1 prompt per intervention_type."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.9),
        _C("c2", "EXECUTION", "reflective", originating_pattern="p2", score=0.85),
        _C("c3", "EMOTIONAL", "emotional", originating_pattern="p3", score=0.80),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme=None)
    reflective_count = sum(1 for s in selected if s.intervention_type == "reflective")
    assert reflective_count <= 1


def test_diversity_max_1_per_originating_pattern_default():
    """Default: max 1 prompt per originating_pattern."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective", originating_pattern="premature_entry", score=0.9),
        _C("c2", "EXECUTION", "tactical", originating_pattern="premature_entry", score=0.85),
        _C("c3", "EMOTIONAL", "emotional", originating_pattern="rule_break", score=0.80),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme=None)
    pe_count = sum(1 for s in selected if s.originating_pattern == "premature_entry")
    assert pe_count <= 1


def test_diversity_higher_score_wins_when_collision():
    """When two candidates compete for the same diversity slot, higher score wins."""
    candidates = [
        _C("low", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.3),
        _C("high", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.9),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme=None)
    selected_ids = {c.candidate_id for c in selected}
    rejected_ids = {c.candidate_id for c in rejected}
    assert "high" in selected_ids
    assert "low" in rejected_ids


# ── 2. Diversity guard — dominant theme override ───────────────────────────


def test_dominant_theme_allows_max_3_per_category():
    """dominant_theme override: max 3 per category."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.9),
        _C("c2", "DISCIPLINE", "tactical", originating_pattern="p2", score=0.85),
        _C("c3", "DISCIPLINE", "emotional", originating_pattern="p3", score=0.80),
        _C("c4", "DISCIPLINE", "future-oriented", originating_pattern="p4", score=0.75),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme="DISCIPLINE")
    discipline_count = sum(1 for s in selected if s.category == "DISCIPLINE")
    assert discipline_count <= 3
    # The 4th DISCIPLINE candidate must be rejected
    rejected_disc = [r for r in rejected if r.category == "DISCIPLINE"]
    assert len(rejected_disc) >= 1


def test_dominant_theme_allows_max_2_per_intervention_type():
    """dominant_theme override: max 2 per intervention_type."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective", originating_pattern="p1", score=0.9),
        _C("c2", "EXECUTION", "reflective", originating_pattern="p2", score=0.85),
        _C("c3", "PATIENCE", "reflective", originating_pattern="p3", score=0.80),
    ]
    selected, rejected = apply_diversity_guards(candidates, dominant_theme="DISCIPLINE")
    reflective_count = sum(1 for s in selected if s.intervention_type == "reflective")
    assert reflective_count <= 2


# ── 3. Coherence pass — contradiction detection ────────────────────────────


def test_coherence_contradiction_pairs_defined():
    """Locked contradiction pairs (CONTEXT.md §4)."""
    pairs_flat: set[str] = set()
    for a, b in CONTRADICTION_PAIRS:
        pairs_flat.add(a)
        pairs_flat.add(b)
    # Must include at least the canonical examples
    assert "too_aggressive" in pairs_flat
    assert "too_passive" in pairs_flat


def test_coherence_detects_aggressive_passive_contradiction():
    """Set with both 'too_aggressive' + 'too_passive' → coherence reduced + swap."""
    contradictory = [
        _C("c1", "DISCIPLINE", "reflective", flags=("too_aggressive",), score=0.9),
        _C("c2", "DISCIPLINE", "tactical", flags=("too_passive",), score=0.85),
        _C("c3", "REGIME", "pattern-recognition", flags=(), score=0.80),
        _C("c4", "READINESS", "future-oriented", temporal_scale="longitudinal", score=0.75),
    ]
    all_candidates = contradictory + [
        _C("alt", "DISCIPLINE", "emotional", flags=(), score=0.70),
    ]
    final, score = coherence_check(contradictory, all_candidates)
    # Either c1 or c2 should be swapped out
    flag_set: set[str] = set()
    for c in final:
        flag_set.update(c.flags)
    assert not ({"too_aggressive", "too_passive"}.issubset(flag_set))
    # Score should reflect that a fix was applied — still in [0,1]
    assert 0.0 <= score <= 1.0


# ── 4. Coherence pass — emotional load budget ──────────────────────────────


def test_coherence_emotional_load_budget_swap():
    """Set whose emotional_load sum > 2.5 swaps the highest-load prompt out."""
    over_budget = [
        _C("hot1", "EMOTIONAL", "emotional", emotional_load=0.9, score=0.9),
        _C("hot2", "DISCIPLINE", "reflective", emotional_load=0.9, score=0.85),
        _C("hot3", "OVERTRADING", "tactical", emotional_load=0.9, score=0.80),
        _C("hot4", "READINESS", "future-oriented",
            temporal_scale="longitudinal", emotional_load=0.9, score=0.75),
    ]
    # sum = 3.6 > 2.5
    pool = over_budget + [
        _C("cool", "REGIME", "pattern-recognition", emotional_load=0.1, score=0.70),
    ]
    final, score = coherence_check(over_budget, pool)
    final_load = sum(c.emotional_load for c in final)
    # After at least one swap the budget must be respected (or signal a lower
    # coherence_score if the pool doesn't have a swap candidate available).
    assert final_load <= 2.5 or score < 0.9


def test_coherence_temporal_mix_requirement():
    """At least 1 immediate-session + 1 longitudinal in final 4-prompt set."""
    all_immediate = [
        _C(f"i{i}", "DISCIPLINE", "reflective",
            temporal_scale="immediate-session", emotional_load=0.4, score=0.9 - i * 0.05)
        for i in range(4)
    ]
    long_alt = _C(
        "long1", "READINESS", "future-oriented",
        temporal_scale="longitudinal", emotional_load=0.4, score=0.5,
    )
    final, score = coherence_check(all_immediate, all_immediate + [long_alt])
    temporal_scales = {c.temporal_scale for c in final}
    # Either the set was mixed in OR the coherence_score reflects the gap
    if "longitudinal" not in temporal_scales:
        # No swap possible (or refused) → coherence penalised
        assert score < 0.9


def test_coherence_score_in_zero_to_one():
    """coherence_score is always in [0.0, 1.0]."""
    candidates = [
        _C("c1", "DISCIPLINE", "reflective",
            temporal_scale="immediate-session", emotional_load=0.4, score=0.9),
        _C("c2", "EXECUTION", "tactical",
            temporal_scale="immediate-session", emotional_load=0.3, score=0.85),
        _C("c3", "REGIME", "pattern-recognition",
            temporal_scale="immediate-session", emotional_load=0.3, score=0.80),
        _C("c4", "READINESS", "future-oriented",
            temporal_scale="longitudinal", emotional_load=0.4, score=0.75),
    ]
    final, score = coherence_check(candidates, candidates)
    assert 0.0 <= score <= 1.0
