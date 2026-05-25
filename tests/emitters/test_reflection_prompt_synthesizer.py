"""Phase 67 Plan 07 — ReflectionPromptSynthesizer tests (Task 2).

Covers the candidate scoring + eligibility filter + selection pipeline
of the synthesizer. Diversity + coherence are exercised in the
companion test_diversity_and_coherence_guards.py file.

Composite score formula (locked by CONTEXT.md §4):
    score = 0.25·severity + 0.20·novelty + 0.20·actionability
          + 0.20·behavioral_confidence + 0.15·longitudinal_relevance

Eligibility filter (multi-domain convergence):
    prompt eligible only if:
        observable trade evidence exists
        AND at least one of [interpretation, pattern, longitudinal] supports it
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from emitters.novelty_engine import NoveltyEngine
from emitters.reflection.assemblers.trade_observation import TradeObservation
from emitters.reflection.assemblers.behavioral_interpretation import (
    BehavioralInterpretation,
)
from emitters.reflection.assemblers.pattern_context import PatternContext
from emitters.reflection.assemblers.longitudinal_context import LongitudinalContext
from emitters.reflection.prompt_library import (
    PROMPT_LIBRARY_VERSION,
    PROMPT_TEMPLATES,
    PromptTemplate,
)
from emitters.reflection.synthesizer import (
    ReflectionPromptSynthesizer,
)


pytestmark = pytest.mark.phase_67


# ── Shared fixtures ────────────────────────────────────────────────────────


def _make_observation(trade_id: str = "t-1", regime: str = "TREND") -> TradeObservation:
    return TradeObservation(
        trade_id=trade_id,
        symbol="EURUSD",
        entry_at=datetime(2026, 5, 25, 9, 15, tzinfo=timezone.utc),
        exit_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        pnl_r=-0.8,
        regime=regime,
        behavioral_tags=("premature_entry",),
    )


def _make_interpretation(
    trade_id: str = "t-1",
    flags: tuple[str, ...] = ("premature_entry",),
    confidence: float = 0.8,
) -> BehavioralInterpretation:
    return BehavioralInterpretation(
        trade_id=trade_id,
        discipline_flags=flags,
        mentor_narrative_summary="Entered before BOS during high compression.",
        confidence=confidence,
    )


def _make_pattern(
    pattern_id: str = "premature_entry_cluster",
    severity: float = 0.7,
) -> PatternContext:
    return PatternContext(
        pattern_id=pattern_id,
        pattern_name=pattern_id,
        supporting_trade_ids=("t-1", "t-2"),
        severity=severity,
    )


def _make_longitudinal() -> LongitudinalContext:
    return LongitudinalContext(
        evolution_trend="worsening",
        adaptive_recommendation="Reduce session size by 25% on choppy days",
        behavioral_trajectory="discipline_drift_4w",
    )


def _real_novelty_engine() -> NoveltyEngine:
    return NoveltyEngine()


# ── 1. Prompt library ──────────────────────────────────────────────────────


def test_prompt_library_has_all_10_categories():
    """Locked taxonomy: DISCIPLINE / EXECUTION / REGIME / EMOTIONAL / LOCATION /
    PATIENCE / OVERTRADING / RISK / READINESS / EDGE_QUALITY."""
    expected = {
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
    }
    assert set(PROMPT_TEMPLATES.keys()) == expected


def test_prompt_library_has_at_least_3_templates_per_category():
    """Each category has ≥3 templates so the synthesizer has selection room."""
    for category, templates in PROMPT_TEMPLATES.items():
        assert len(templates) >= 3, (
            f"Category {category!r} has only {len(templates)} templates "
            "(must be >=3 per plan)"
        )


def test_prompt_library_total_count_30_or_more():
    """Plan asks for ~30-50 templates total across 10 categories."""
    total = sum(len(v) for v in PROMPT_TEMPLATES.values())
    assert total >= 30, f"Total templates {total} < 30 (plan target 30-50)"


def test_prompt_library_no_generic_prompts():
    """Regression: locked anti-pattern — no 'how did you feel' / 'what went well'."""
    forbidden_substrings = (
        "how did you feel",
        "what went well",
    )
    for category, templates in PROMPT_TEMPLATES.items():
        for tpl in templates:
            lower = tpl.template.lower()
            for forbidden in forbidden_substrings:
                assert forbidden not in lower, (
                    f"Generic prompt forbidden — found {forbidden!r} in "
                    f"{category} template: {tpl.template!r}"
                )


def test_prompt_library_template_dataclass_is_frozen():
    """PromptTemplate is a frozen dataclass."""
    t = next(iter(PROMPT_TEMPLATES["DISCIPLINE"]))
    with pytest.raises(Exception):
        t.template = "mutated"  # type: ignore[misc]


def test_prompt_library_version_string():
    """PROMPT_LIBRARY_VERSION present and looks like v#.#.#"""
    assert isinstance(PROMPT_LIBRARY_VERSION, str)
    assert PROMPT_LIBRARY_VERSION.startswith("v")
    # rough semver shape
    parts = PROMPT_LIBRARY_VERSION.lstrip("v").split(".")
    assert len(parts) == 3


def test_prompt_template_interventions_are_valid():
    """Every template's intervention_type is in the locked taxonomy."""
    valid_types = {
        "reflective",
        "tactical",
        "pattern-recognition",
        "emotional",
        "future-oriented",
    }
    for category, templates in PROMPT_TEMPLATES.items():
        for t in templates:
            assert t.intervention_type in valid_types, (
                f"{category} template has invalid intervention_type={t.intervention_type!r}"
            )


def test_prompt_template_strengths_are_valid():
    """Every template's default_strength is in the locked taxonomy."""
    valid = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
    for category, templates in PROMPT_TEMPLATES.items():
        for t in templates:
            assert t.default_strength in valid, (
                f"{category} template has invalid default_strength={t.default_strength!r}"
            )


# ── 2. Composite score formula ─────────────────────────────────────────────


def test_score_formula_weights_lock():
    """Composite weights are locked per CONTEXT.md §4."""
    syn = ReflectionPromptSynthesizer()
    weights = syn.DEFAULT_WEIGHTS
    assert weights["severity"] == 0.25
    assert weights["novelty"] == 0.20
    assert weights["actionability"] == 0.20
    assert weights["behavioral_confidence"] == 0.20
    assert weights["longitudinal_relevance"] == 0.15
    # Weights sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_score_candidate_pure_function():
    """_score_candidate is deterministic for same input."""
    syn = ReflectionPromptSynthesizer()
    factors = dict(
        severity=0.8, novelty=0.5, actionability=0.7,
        behavioral_confidence=0.9, longitudinal_relevance=0.4,
    )
    s1 = syn._score_candidate(factors)
    s2 = syn._score_candidate(factors)
    assert s1 == s2
    # 0.25*0.8 + 0.20*0.5 + 0.20*0.7 + 0.20*0.9 + 0.15*0.4
    # = 0.20 + 0.10 + 0.14 + 0.18 + 0.06 = 0.68
    assert abs(s1 - 0.68) < 1e-9


# ── 3. Eligibility filter (multi-domain convergence) ───────────────────────


def test_eligibility_requires_observation():
    """No observations → no eligible candidates (zero prompts)."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[],
        interpretations=[_make_interpretation()],
        patterns=[_make_pattern()],
        longitudinal=[_make_longitudinal()],
        novelty_engine=_real_novelty_engine(),
    )
    assert result.selected_prompts == []


def test_eligibility_requires_at_least_one_supporting_layer():
    """Observation alone (no interpretation/pattern/longitudinal) → zero prompts."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[_make_observation()],
        interpretations=[],
        patterns=[],
        longitudinal=[],
        novelty_engine=_real_novelty_engine(),
    )
    assert result.selected_prompts == []


def test_eligibility_passes_with_interpretation_layer():
    """Observation + interpretation → at least one eligible prompt."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[_make_observation()],
        interpretations=[_make_interpretation()],
        patterns=[],
        longitudinal=[],
        novelty_engine=_real_novelty_engine(),
    )
    # At least one prompt should be generated when discipline_flags present
    assert len(result.selected_prompts) >= 1


# ── 4. Selection ordering + count ──────────────────────────────────────────


def test_selected_prompts_capped_at_4():
    """Maximum 4 selected prompts per session set."""
    syn = ReflectionPromptSynthesizer()
    # Generate many observations + interpretations + patterns
    observations = [_make_observation(f"t-{i}") for i in range(10)]
    interpretations = [
        _make_interpretation(
            trade_id=f"t-{i}",
            flags=("premature_entry", "size_violation", "regime_mismatch", "rule_break"),
        )
        for i in range(10)
    ]
    patterns = [
        _make_pattern(f"pattern-{i}", severity=0.5 + i * 0.05) for i in range(5)
    ]
    result = syn.synthesize(
        account_id=42,
        observations=observations,
        interpretations=interpretations,
        patterns=patterns,
        longitudinal=[_make_longitudinal()],
        novelty_engine=_real_novelty_engine(),
    )
    assert len(result.selected_prompts) <= 4


def test_rejected_candidates_persisted_with_reason():
    """Rejected candidates persisted with selected=False + rejection_reason."""
    syn = ReflectionPromptSynthesizer()
    observations = [_make_observation(f"t-{i}") for i in range(10)]
    interpretations = [
        _make_interpretation(
            trade_id=f"t-{i}",
            flags=("premature_entry", "size_violation", "regime_mismatch"),
        )
        for i in range(10)
    ]
    patterns = [
        _make_pattern(f"pattern-{i}", severity=0.6 + i * 0.05) for i in range(5)
    ]
    result = syn.synthesize(
        account_id=42,
        observations=observations,
        interpretations=interpretations,
        patterns=patterns,
        longitudinal=[_make_longitudinal()],
        novelty_engine=_real_novelty_engine(),
    )

    # Expect at least a few rejected candidates given the volume
    assert len(result.rejected_candidates) >= 1
    for rej in result.rejected_candidates:
        assert rej.selected is False
        assert rej.rejection_reason  # non-empty


def test_selected_prompts_sorted_descending_by_score():
    """Selected prompts ordered by composite score (descending)."""
    syn = ReflectionPromptSynthesizer()
    observations = [_make_observation(f"t-{i}") for i in range(5)]
    interpretations = [
        _make_interpretation(
            trade_id=f"t-{i}",
            flags=("premature_entry", "size_violation", "regime_mismatch"),
        )
        for i in range(5)
    ]
    patterns = [
        _make_pattern(f"pattern-{i}", severity=0.5 + i * 0.05) for i in range(3)
    ]
    result = syn.synthesize(
        account_id=42,
        observations=observations,
        interpretations=interpretations,
        patterns=patterns,
        longitudinal=[_make_longitudinal()],
        novelty_engine=_real_novelty_engine(),
    )

    scores = [p.confidence_score for p in result.selected_prompts]
    assert scores == sorted(scores, reverse=True)


# ── 5. Contract field stamping ─────────────────────────────────────────────


def test_prompt_version_stamped_from_library():
    """Each prompt carries prompt_version from PROMPT_LIBRARY_VERSION."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[_make_observation()],
        interpretations=[_make_interpretation()],
        patterns=[],
        longitudinal=[],
        novelty_engine=_real_novelty_engine(),
    )
    for p in result.selected_prompts:
        assert p.prompt_version == PROMPT_LIBRARY_VERSION


def test_evidence_chain_structured_as_kind_ref_weight():
    """evidence_chain[] items are {kind, ref, weight} dicts/dataclass instances."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[_make_observation()],
        interpretations=[_make_interpretation()],
        patterns=[_make_pattern()],
        longitudinal=[],
        novelty_engine=_real_novelty_engine(),
    )
    assert len(result.selected_prompts) >= 1
    for p in result.selected_prompts:
        assert isinstance(p.evidence_chain, list)
        for item in p.evidence_chain:
            assert item.kind in {
                "discipline_flag",
                "cross_trade_pattern",
                "regime",
                "behavioral_evolution",
                "execution_trace",
                "readiness",
                "mentor_narrative",
            }
            assert isinstance(item.ref, str)
            assert 0.0 <= item.weight <= 1.0


def test_base_prompt_and_llm_enriched_both_present_when_crossed():
    """base_prompt ALWAYS set; llm_enriched_prompt populated when novelty crossed."""
    syn = ReflectionPromptSynthesizer()
    # Force novelty crossed via MagicMock engine
    fake_engine = MagicMock()
    fake_engine.score = MagicMock(
        return_value=MagicMock(score=0.9, threshold_crossed=True, reason_codes=["MACRO"])
    )
    # Patch LLM enrichment to return a known string
    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            ReflectionPromptSynthesizer,
            "_call_llm",
            lambda self, base, ctx: f"[ENRICHED] {base}",
        )
        result = syn.synthesize(
            account_id=42,
            observations=[_make_observation()],
            interpretations=[_make_interpretation()],
            patterns=[_make_pattern()],
            longitudinal=[_make_longitudinal()],
            novelty_engine=fake_engine,
        )
    for p in result.selected_prompts:
        assert p.base_prompt  # always non-empty
        # When novelty crossed, llm_enriched_prompt should be populated
        assert p.llm_enriched_prompt is not None
        assert "[ENRICHED]" in p.llm_enriched_prompt


def test_llm_does_not_change_category_or_intervention_strength():
    """LLM enrichment is additive — category + strength + intervention_type LOCKED."""
    syn = ReflectionPromptSynthesizer()
    fake_engine = MagicMock()
    fake_engine.score = MagicMock(
        return_value=MagicMock(score=0.9, threshold_crossed=True, reason_codes=["X"])
    )

    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            ReflectionPromptSynthesizer,
            "_call_llm",
            # Return enriched text only — synthesizer must NOT let this
            # mutate any locked field.
            lambda self, base, ctx: "ENRICHED",
        )
        result = syn.synthesize(
            account_id=42,
            observations=[_make_observation()],
            interpretations=[_make_interpretation()],
            patterns=[_make_pattern()],
            longitudinal=[],
            novelty_engine=fake_engine,
        )

    for p in result.selected_prompts:
        # locked literal taxonomy
        assert p.category in {
            "DISCIPLINE", "EXECUTION", "REGIME", "EMOTIONAL", "LOCATION",
            "PATIENCE", "OVERTRADING", "RISK", "READINESS", "EDGE_QUALITY",
        }
        assert p.intervention_strength in {"LOW", "MODERATE", "HIGH", "CRITICAL"}
        assert p.intervention_type in {
            "reflective", "tactical", "pattern-recognition", "emotional", "future-oriented",
        }


# ── 6. Set-level contract output ───────────────────────────────────────────


def test_synthesize_returns_set_contract_with_set_id():
    """Output carries set_id + account_id + generated_at + coherence_score."""
    syn = ReflectionPromptSynthesizer()
    result = syn.synthesize(
        account_id=42,
        observations=[_make_observation()],
        interpretations=[_make_interpretation()],
        patterns=[],
        longitudinal=[],
        novelty_engine=_real_novelty_engine(),
    )
    assert result.set_id
    assert result.account_id == 42
    assert result.generated_at
    assert 0.0 <= result.reflection_set_coherence_score <= 1.0
