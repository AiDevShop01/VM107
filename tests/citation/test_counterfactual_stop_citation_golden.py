"""Phase 61-02 Task 5 — test_counterfactual_stop_citation_golden.py

Citation golden tests for the 5 canonical stop scenario citations.

Verifies:
  - Citation grammar parses correctly for all 5 stop scenario citation forms
  - CitationValidator resolves known scenario_ids against populated registry
  - Adversarial fixtures: unknown scenario_id → CitationViolation
  - Phase 60 backward-compat: existing citation forms still validate (RG-3)

RG-3 coverage (golden citation tests).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# VM107 root setup
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIVE_CANONICAL_SCENARIO_IDS = [
    "counterfactual.stop.atr_0_5",
    "counterfactual.stop.atr_1_0",
    "counterfactual.stop.atr_1_5",
    "counterfactual.stop.liquidity_buffer",
    "counterfactual.stop.session_range",
]

_COUNTERFACTUAL_FIELDS = [
    "hypothetical_r",
    "hypothetical_exit_price",
    "hypothetical_mae_r",
    "hypothetical_mfe_r",
    "divergence_frame_id",
]


def _make_registry_with_five_scenarios() -> Path:
    """Create a temporary registry dir with all 5 canonical stop scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _FIVE_CANONICAL_SCENARIO_IDS:
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


def test_all_five_stop_scenario_citation_forms_parse_correctly():
    """All 5 canonical stop scenario citations parse syntactically (RG-3).

    Grammar: [ref:counterfactual:<scenario_id>:<outcome_field>]
    The field segment permits dots for dotted scenario_ids (Phase 61-01 Option B).
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    for scenario_id in _FIVE_CANONICAL_SCENARIO_IDS:
        citation = f"[ref:counterfactual:{scenario_id}:hypothetical_r]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}: {tokens}"
        )
        assert tokens[0].registry_id == "counterfactual", (
            f"registry_id should be 'counterfactual', got {tokens[0].registry_id!r}"
        )
        assert tokens[0].field == f"{scenario_id}:hypothetical_r", (
            f"field should be '{scenario_id}:hypothetical_r', got {tokens[0].field!r}"
        )


def test_all_outcome_fields_parse_correctly():
    """All 5 counterfactual outcome fields parse correctly for atr_1_5 scenario."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    scenario_id = "counterfactual.stop.atr_1_5"
    for field in _COUNTERFACTUAL_FIELDS:
        citation = f"[ref:counterfactual:{scenario_id}:{field}]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}"
        )
        assert f"{scenario_id}:{field}" in tokens[0].field or tokens[0].field == f"{scenario_id}:{field}", (
            f"field mismatch: expected '{scenario_id}:{field}', got {tokens[0].field!r}"
        )


def test_artifact_level_citation_form_parses():
    """Artifact-level citation [ref:counterfactual:cf_<uuid>] parses correctly."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation = "[ref:counterfactual:cf_550e8400e29b41d4a716446655440000]"
    tokens = parse_citation_tokens(citation)
    assert len(tokens) == 1, f"Expected 1 token, got {len(tokens)}: {tokens}"
    assert tokens[0].registry_id == "counterfactual"
    assert tokens[0].field.startswith("cf_")


# ---------------------------------------------------------------------------
# Validator tests (CitationValidator — registry lookup)
# ---------------------------------------------------------------------------


def test_validator_resolves_atr_1_5_scenario_citation():
    """CitationValidator passes [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r].

    This is the primary Phase 61-02 first-citation golden test.
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

    registry_root = _make_registry_with_five_scenarios()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under the counterfactual stop scenario at 1.5x ATR, "
        "hypothetical R was 2.3 [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]."
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

    # Should NOT raise — scenario_id is registered
    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r] "
            f"when scenario is in registry. Got violation: {exc}"
        )


def test_validator_resolves_all_five_stop_scenario_citations():
    """All 5 stop scenario citations resolve cleanly against the populated registry.

    Phase 61-02 golden test: once 5 YAMLs ship, all 5 citation forms must validate.
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

    registry_root = _make_registry_with_five_scenarios()
    validator = CitationValidator(registry_root)

    for scenario_id in _FIVE_CANONICAL_SCENARIO_IDS:
        citation_text = (
            f"Under the counterfactual stop scenario, "
            f"hypothetical R was 2.3 "
            f"[ref:counterfactual:{scenario_id}:hypothetical_r]."
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
                f"CitationValidator should pass [ref:counterfactual:{scenario_id}:hypothetical_r]. "
                f"Got violation: {exc}"
            )


def test_validator_hard_fails_on_unknown_scenario_id():
    """Adversarial: [ref:counterfactual:counterfactual.stop.atr_2_0:hypothetical_r] raises.

    counterfactual.stop.atr_2_0 is NOT in the registry (not a shipped scenario).
    Law #7: scenario_version bumps create new scenario_ids — atr_2_0 is distinct.
    This test verifies the hard-fail on unknown scenario_ids.
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

    registry_root = _make_registry_with_five_scenarios()
    validator = CitationValidator(registry_root)

    # atr_2_0 is NOT registered — should cause CitationViolation
    unknown_citation = (
        "Hypothetical R [ref:counterfactual:counterfactual.stop.atr_2_0:hypothetical_r]."
    )
    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=unknown_citation,
        citations=parse_citation_tokens(unknown_citation),
    )
    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )

    with pytest.raises(CitationViolation) as exc_info:
        validator.enforce(envelope)

    assert "atr_2_0" in str(exc_info.value), (
        f"CitationViolation message should mention the unknown scenario_id 'atr_2_0'. "
        f"Got: {exc_info.value}"
    )


def test_artifact_level_citation_passes_without_registry_lookup():
    """[ref:counterfactual:cf_<uuid>] passes without scenario registry lookup.

    Artifact-level citations use cf_ prefix — validator skips registry check.
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

    # Empty registry (no scenarios registered) — artifact-level should still pass
    empty_registry = Path(tempfile.mkdtemp())

    validator = CitationValidator(empty_registry)

    citation_text = (
        "See artifact [ref:counterfactual:cf_550e8400e29b41d4a716446655440000] for details."
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
            f"Artifact-level cf_ citations should not require scenario registry lookup. "
            f"Got violation: {exc}"
        )


def test_phase60_backward_compat_citations_still_valid(tmp_path):
    """Phase 60 citation forms still validate after Phase 61 grammar extension (RG-3).

    All existing Phase 60 [ref:behavioral_pattern:X], [ref:signal:Y], etc.
    must continue to parse and validate correctly.
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

    # Build a registry with Phase 60 IDs
    # NOTE: In the citation grammar, registry_id IS the YAML id field (not the subdir name).
    # [ref:revenge_trade:entry_delay_ms] — where 'revenge_trade' is the yaml id.
    # [ref:hesitation_entry:severity@frame_5] — where 'hesitation_entry' is the yaml id.
    (tmp_path / "behavioral_pattern").mkdir()
    (tmp_path / "behavioral_pattern" / "revenge_trade.yaml").write_text(
        "id: revenge_trade\ntype: behavioral_pattern\n"
    )
    (tmp_path / "signal").mkdir()
    (tmp_path / "signal" / "hesitation_entry.yaml").write_text(
        "id: hesitation_entry\ntype: signal\n"
    )

    validator = CitationValidator(tmp_path)

    # Phase 60 citation form: [ref:<yaml-id>:<field>] where yaml-id = YAML's 'id' field
    golden_citations = [
        "Trade showed [ref:revenge_trade:entry_delay_ms] behavior.",
        "Signal detected [ref:hesitation_entry:severity@frame_5] at entry.",
    ]

    for text in golden_citations:
        sentence = NarrativeSentence(
            sentence_index=0,
            sentence_class=SentenceClass.ASSERTION,
            text=text,
            citations=parse_citation_tokens(text),
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
                f"Phase 60 citation {text!r} failed after Phase 61 extension (RG-3). "
                f"Backward-compat violated: {exc}"
            )
