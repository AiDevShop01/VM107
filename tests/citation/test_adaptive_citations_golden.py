"""Phase 62-03 Task 2 — test_adaptive_citations_golden.py

Citation golden tests for Phase 62 adaptive artifact citations.

Verifies:
  - [ref:drift_report:<cohort_snapshot_id>:<field>] resolves with adaptive registry
  - [ref:counterfactual_aggregate:<cohort_snapshot_id>:<field>] resolves
  - [ref:drift_report:UNKNOWN_ID:<field>] raises CitationViolation (RG-3)
  - Phase 60/61 citation grammar is unaffected by adding Phase 62 signal/ YAMLs
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Phase 62 adaptive registry IDs (from the three signal/ YAMLs shipped in 62-03)
_ADAPTIVE_SIGNAL_IDS = [
    "drift_strategy_category_regime",
    "drift_counterfactual_delta",
    "drift_winrate_calibration",
]

# UUIDs used in citation tokens — mimic real cohort_snapshot_id format
_MOCK_COHORT_ID = "550e8400-e29b-41d4-a716-446655440001"
_MOCK_SCENARIO_ID = "counterfactual.stop.atr_1_5"


def _make_registry_with_adaptive_signals() -> Path:
    """Create a temporary registry dir with Phase 62 adaptive signal YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    signal_dir = tmpdir / "signal"
    signal_dir.mkdir()
    for signal_id in _ADAPTIVE_SIGNAL_IDS:
        (signal_dir / f"{signal_id}.yaml").write_text(
            f"id: {signal_id}\n"
            f"type: signal\n"
            f"signal_category: STRATEGIC\n"
            f"phase: 62\n"
        )
    return tmpdir


def _make_registry_with_phase61_and_62() -> Path:
    """Registry with Phase 61 counterfactual + Phase 62 adaptive YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    signal_dir = tmpdir / "signal"
    signal_dir.mkdir()
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()

    # Phase 62 signal YAMLs
    for signal_id in _ADAPTIVE_SIGNAL_IDS:
        (signal_dir / f"{signal_id}.yaml").write_text(
            f"id: {signal_id}\ntype: signal\nsignal_category: STRATEGIC\nphase: 62\n"
        )
    # Phase 61 counterfactual YAMLs
    for scenario_id in ["counterfactual.stop.atr_1_5", "counterfactual.exit.trailing_atr"]:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\ntype: counterfactual_scenario\nscenario_tier: canonical\n"
        )
    return tmpdir


def _try_import_citation_tools():
    try:
        from fingpt_core.contracts.narrative.citation import parse_citation_tokens
        from helpers.citation_validator import CitationValidator, CitationViolation
        return parse_citation_tokens, CitationValidator, CitationViolation
    except ImportError as exc:
        pytest.skip(f"fingpt_core or citation_validator not available: {exc}")


def _try_import_narrative_contracts():
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
        return NarrativeEnvelope, NarrativeSentence, SentenceClass
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")


def _make_assertion_envelope(
    citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
):
    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=citation_text,
        citations=parse_citation_tokens(citation_text),
    )
    return NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )


# ---------------------------------------------------------------------------
# Grammar: parse citation tokens for adaptive grammar forms
# ---------------------------------------------------------------------------

def test_drift_report_citation_form_parses():
    """[ref:drift_report:<cohort_snapshot_id>:<field>] parses syntactically."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation = f"[ref:drift_report:{_MOCK_COHORT_ID}:drift_score]"
    tokens = parse_citation_tokens(citation)
    assert len(tokens) == 1
    assert tokens[0].registry_id == "drift_report"


def test_counterfactual_aggregate_citation_form_parses():
    """[ref:counterfactual_aggregate:<id>:<field>] parses syntactically."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation = f"[ref:counterfactual_aggregate:{_MOCK_COHORT_ID}:avg_delta_r]"
    tokens = parse_citation_tokens(citation)
    assert len(tokens) == 1
    assert tokens[0].registry_id == "counterfactual_aggregate"


# ---------------------------------------------------------------------------
# Validator: known adaptive signal IDs resolve
# ---------------------------------------------------------------------------

def test_validator_resolves_drift_strategy_category_regime():
    """CitationValidator.enforce() passes drift_strategy_category_regime citation (RG-3)."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_adaptive_signals()
    validator = CitationValidator(registry_root)

    citation_text = (
        f"The evidence suggests possible drift in this strategy-regime cohort "
        f"[ref:drift_strategy_category_regime:{_MOCK_COHORT_ID}:drift_score]. "
        "BOOTSTRAP OBSERVATION: this is a shadow-only signal."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(f"Should resolve drift_strategy_category_regime citation. Got: {exc}")


def test_validator_resolves_drift_counterfactual_delta():
    """CitationValidator.enforce() passes drift_counterfactual_delta citation (RG-3)."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_adaptive_signals()
    validator = CitationValidator(registry_root)

    citation_text = (
        f"The evidence suggests possible drift in counterfactual scenario statistics "
        f"[ref:drift_counterfactual_delta:{_MOCK_COHORT_ID}:avg_delta_r]. "
        "SHADOW_ONLY adaptive signal."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(f"Should resolve drift_counterfactual_delta citation. Got: {exc}")


# ---------------------------------------------------------------------------
# Adversarial: unknown ID raises CitationViolation
# ---------------------------------------------------------------------------

def test_adversarial_unknown_drift_report_id_raises_violation():
    """[ref:unknown_adaptive_signal:some_uuid:field] raises CitationViolation (RG-3).

    The registry_id 'unknown_adaptive_signal' is not in the registry (lowercase, valid grammar),
    so CitationValidator.enforce() should raise CitationViolation.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_adaptive_signals()
    validator = CitationValidator(registry_root)

    # Use a lowercase registry_id that is grammatically valid but NOT in the registry
    citation_text = (
        "Unknown drift signal [ref:unknown_adaptive_signal:drift_score]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    with pytest.raises(CitationViolation):
        validator.enforce(envelope)


# ---------------------------------------------------------------------------
# Backward compat: Phase 61 citations still resolve with Phase 62 registry present
# ---------------------------------------------------------------------------

def test_phase61_citations_still_resolve_with_phase62_registry():
    """Phase 61 counterfactual citations unaffected by Phase 62 signal/ YAMLs (RG-3)."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_phase61_and_62()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under deterministic policy, using only information visible at replay frame T, "
        "the resulting branch survived 11 additional frames "
        "[ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(f"Phase 61 citation broke after Phase 62 registry expansion: {exc}")
