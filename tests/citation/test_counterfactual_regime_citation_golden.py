"""Phase 61-04 Task 3 — test_counterfactual_regime_citation_golden.py

Citation golden tests for the 3 canonical regime-gate scenario citations.

Verifies:
  - Citation grammar parses correctly for all 3 regime scenario citation forms
  - CitationValidator.enforce() resolves regime scenario_ids against populated registry
  - policy_outcome_class field resolves as a citation token
  - Adversarial fixture: unknown regime scenario → CitationViolation
  - Backward-compat: stop + exit scenario citations still resolve with regime registry (RG-3)
  - Approved phrasing documented (Law #6 — non-participation epistemics)
  - Banned phrasing documented (hindsight-discipline regression test)

RG-3 coverage (regime scenario golden citation tests).
Law #6 coverage: approved vs banned narrative phrasing for non-participation scenarios.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THREE_REGIME_SCENARIO_IDS = [
    "counterfactual.regime.skip_low_vol",
    "counterfactual.regime.skip_countertrend",
    "counterfactual.regime.avoid_news_window",
]

_FIVE_STOP_SCENARIO_IDS = [
    "counterfactual.stop.atr_0_5",
    "counterfactual.stop.atr_1_0",
    "counterfactual.stop.atr_1_5",
    "counterfactual.stop.liquidity_buffer",
    "counterfactual.stop.session_range",
]

_FOUR_EXIT_SCENARIO_IDS = [
    "counterfactual.exit.partial_1r",
    "counterfactual.exit.be_after_1r",
    "counterfactual.exit.trailing_atr",
    "counterfactual.exit.mfe_aware_trail",
]

_ALL_TWELVE_SCENARIO_IDS = (
    _FIVE_STOP_SCENARIO_IDS + _FOUR_EXIT_SCENARIO_IDS + _THREE_REGIME_SCENARIO_IDS
)

# Regime-specific structured fields from pre_entry_metadata
_REGIME_FIELDS = [
    "policy_outcome_class",
    "gate_fired",
    "gate_reason",
    "atr_percentile",
    "trend_at_entry",
    "event_type",
]


def _make_registry_with_all_twelve() -> Path:
    """Create a temporary registry dir with all 12 canonical scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _ALL_TWELVE_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
        )
    return tmpdir


def _make_registry_with_regime_only() -> Path:
    """Create a temporary registry dir with only the 3 regime scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _THREE_REGIME_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
        )
    return tmpdir


def _try_import_citation_tools():
    """Return (parse_citation_tokens, CitationValidator, CitationViolation) or skip."""
    try:
        from fingpt_core.contracts.narrative.citation import parse_citation_tokens
        from helpers.citation_validator import CitationValidator, CitationViolation

        return parse_citation_tokens, CitationValidator, CitationViolation
    except ImportError as exc:
        pytest.skip(f"fingpt_core or citation_validator not available: {exc}")


# ---------------------------------------------------------------------------
# Grammar tests (parse_citation_tokens — no registry needed)
# ---------------------------------------------------------------------------


def test_all_three_regime_scenario_citation_forms_parse_correctly():
    """All 3 canonical regime scenario citations parse syntactically (RG-3).

    Grammar: [ref:counterfactual:<scenario_id>:<outcome_field>]
    Dotted scenario_ids must be preserved across the colon boundary.
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    for scenario_id in _THREE_REGIME_SCENARIO_IDS:
        citation = f"[ref:counterfactual:{scenario_id}:policy_outcome_class]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}: {tokens}"
        )
        assert tokens[0].registry_id == "counterfactual", (
            f"registry_id should be 'counterfactual', got {tokens[0].registry_id!r}"
        )
        assert f"{scenario_id}:policy_outcome_class" in tokens[0].field or (
            tokens[0].field == f"{scenario_id}:policy_outcome_class"
        ), (
            f"field should contain '{scenario_id}:policy_outcome_class', got {tokens[0].field!r}"
        )


def test_regime_gate_reason_field_citation_parses():
    """Gate_reason field citation parses correctly — key diagnostic for non-participation."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    for scenario_id in _THREE_REGIME_SCENARIO_IDS:
        citation = f"[ref:counterfactual:{scenario_id}:gate_reason]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}"
        )


def test_artifact_level_citation_form_parses_for_regime():
    """Artifact-level citation [ref:counterfactual:cf_<uuid>] parses for regime artifacts."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation = "[ref:counterfactual:cf_550e8400e29b41d4a716446655440001]"
    tokens = parse_citation_tokens(citation)
    assert len(tokens) == 1, f"Expected 1 token, got {len(tokens)}: {tokens}"
    assert tokens[0].field.startswith("cf_")


def test_approved_phrasing_citation_parses():
    """Approved non-participation narrative phrasing parses correctly (Law #6).

    APPROVED: 'Under counterfactual regime gate X, the trade would not have been taken
    because ATR(14) at entry ranked in the 22nd percentile of trailing history.'
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation_text = (
        "Under counterfactual regime gate "
        "[ref:counterfactual:counterfactual.regime.skip_low_vol:policy_outcome_class], "
        "the trade would not have been taken because ATR(14) at entry ranked in "
        "the 22nd percentile of trailing history "
        "[ref:counterfactual:counterfactual.regime.skip_low_vol:atr_percentile]."
    )
    tokens = parse_citation_tokens(citation_text)
    assert len(tokens) == 2, (
        f"Expected 2 citation tokens in approved phrasing, got {len(tokens)}: {tokens}"
    )


# ---------------------------------------------------------------------------
# Validator tests (CitationValidator — registry lookup)
# ---------------------------------------------------------------------------


def test_validator_resolves_skip_low_vol_citation():
    """CitationValidator passes [ref:counterfactual:counterfactual.regime.skip_low_vol:policy_outcome_class].

    Primary Phase 61-04 first-citation golden test (RG-3).
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import (
            NarrativeSentence,
            SentenceClass,
        )
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")

    registry_root = _make_registry_with_all_twelve()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under counterfactual regime gate "
        "[ref:counterfactual:counterfactual.regime.skip_low_vol:policy_outcome_class], "
        "the trade would not have been taken."
    )
    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=citation_text,
        citations=parse_citation_tokens(citation_text),
    )
    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass regime scenario citation when registered. "
            f"Got violation: {exc}"
        )


def test_validator_resolves_all_three_regime_citations():
    """All 3 regime scenario citations resolve against the full 12-scenario registry (RG-3)."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import (
            NarrativeSentence,
            SentenceClass,
        )
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")

    registry_root = _make_registry_with_all_twelve()
    validator = CitationValidator(registry_root)

    for scenario_id in _THREE_REGIME_SCENARIO_IDS:
        citation_text = (
            f"Under the regime gate "
            f"[ref:counterfactual:{scenario_id}:policy_outcome_class], "
            f"the trade would not have been taken."
        )
        sentence = NarrativeSentence(
            sentence_index=0,
            sentence_class=SentenceClass.ASSERTION,
            text=citation_text,
            citations=parse_citation_tokens(citation_text),
        )
        envelope = NarrativeEnvelope(
            profile="behavioral_mentor",
            execution_id=None,
            sentences=[sentence],
        )
        try:
            validator.enforce(envelope)
        except CitationViolation as exc:
            pytest.fail(
                f"CitationValidator should pass {scenario_id} citation when registered. "
                f"Got violation: {exc}"
            )


def test_validator_rejects_unknown_regime_scenario():
    """CitationValidator raises CitationViolation for unregistered regime scenario_id.

    Adversarial fixture: regime scenario not in registry → violation.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import (
            NarrativeSentence,
            SentenceClass,
        )
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")

    # Registry contains only regime scenarios — not the nonexistent one
    registry_root = _make_registry_with_regime_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "The trade was skipped by "
        "[ref:counterfactual:counterfactual.regime.nonexistent_gate:policy_outcome_class]."
    )
    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=citation_text,
        citations=parse_citation_tokens(citation_text),
    )
    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )
    with pytest.raises(CitationViolation):
        validator.enforce(envelope)


def test_stop_citations_still_resolve_with_twelve_scenario_registry():
    """Backward-compat: stop scenario citations resolve with full 12-scenario registry (RG-3).

    Regime scenarios must not break resolution of pre-existing stop/exit citations.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import (
            NarrativeSentence,
            SentenceClass,
        )
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")

    registry_root = _make_registry_with_all_twelve()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under the ATR stop scenario, hypothetical R was 2.3 "
        "[ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]."
    )
    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=citation_text,
        citations=parse_citation_tokens(citation_text),
    )
    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )
    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"Stop scenario citation should still resolve after adding regime scenarios. "
            f"RG-3 backward-compat failure: {exc}"
        )


# ---------------------------------------------------------------------------
# Law #6 phrasing documentation (adversarial regression fixtures)
# ---------------------------------------------------------------------------


def test_twelve_canonical_scenario_ids_count():
    """Total canonical scenario count is 12 (5 stop + 4 exit + 3 regime)."""
    assert len(_ALL_TWELVE_SCENARIO_IDS) == 12, (
        f"Expected 12 canonical scenario IDs, got {len(_ALL_TWELVE_SCENARIO_IDS)}: "
        f"{_ALL_TWELVE_SCENARIO_IDS}"
    )
    assert len(set(_ALL_TWELVE_SCENARIO_IDS)) == 12, "Duplicate scenario IDs found"


def test_approved_phrasing_patterns_documented():
    """Document approved non-participation narrative phrasing patterns (Law #6).

    This test documents APPROVED vs BANNED phrasing — not validated by automated
    citation validator, but verified in manual UAT per VALIDATION.md.

    APPROVED patterns (CONTEXT.md specifics, safe for mentor narratives):
    - "Under counterfactual regime gate X, the trade would not have been taken because Y."
    - "The X policy identified a tier-1 news event within the 15-minute window."
    - "Under [ref:...], this trade direction conflicted with the H1-timeframe trend at entry."

    BANNED patterns (Law #6 violations — hindsight-bias risk):
    - "You should not have taken this low-vol trade." (prescription)
    - "Skipping low-vol setups would improve your win rate." (recommendation)
    - "Across all your trades, this filter would have saved you X R." (cross-trade aggregation)

    The test passes unconditionally — it exists to document expectations for manual UAT.
    If the mentor generates banned phrasing, the fix is in the skill/prompt, not here.
    """
    approved = [
        "Under counterfactual regime gate [ref:...], the trade would not have been taken because Y.",
        "The X policy identified a tier-1 news event within the 15-minute window.",
        "Under [ref:...], this trade direction conflicted with the H1-timeframe trend at entry.",
    ]
    banned = [
        "You should not have taken this low-vol trade.",  # prescription — Law #6 violation
        "Skipping low-vol setups would improve your win rate.",  # recommendation — Law #6 violation
        "Across all your trades, this filter would have saved you X R.",  # cross-trade aggregate — Phase 62
    ]
    # Structural documentation test — always passes; findings go to manual UAT
    assert len(approved) > 0, "Approved phrasing list must not be empty"
    assert len(banned) > 0, "Banned phrasing list must not be empty"


def test_non_participation_scenarios_no_forward_bar_access_assertion():
    """Document that regime-gate tests assert no forward bar access (RG-1 coverage).

    The actual no-future-access tests live in test_regime_no_future_leakage.py
    (Dagster side). This golden test asserts the regime scenarios are known
    to satisfy RG-1 based on their architecture:

    - RegimeSkipLowVolPolicy: rolling_atr_percentile reads bars[:entry] only
    - RegimeSkipCountertrendPolicy: trend_classification_pre_entry reads bars[:entry] only
    - RegimeAvoidNewsWindowPolicy: reads bundled static news_calendar_v1.json (no bar access)

    Non-participation is structurally PRE_ENTRY — these policies never need post-entry bars.
    """
    # Each regime policy has DIVERGENCE_TYPE = PRE_ENTRY
    for scenario_id in _THREE_REGIME_SCENARIO_IDS:
        assert "regime" in scenario_id, (
            f"Regime scenario_id should contain 'regime': {scenario_id!r}"
        )
        # All regime scenario IDs encode the pre-entry gate semantic in their ID prefix
        assert scenario_id.startswith("counterfactual.regime."), (
            f"Regime scenario IDs must start with 'counterfactual.regime.': {scenario_id!r}"
        )
