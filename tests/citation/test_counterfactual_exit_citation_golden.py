"""Phase 61-03 Task 3 — test_counterfactual_exit_citation_golden.py

Citation golden tests for the 4 canonical exit scenario citations.

Verifies:
  - Citation grammar parses correctly for all 4 exit scenario citation forms
  - CitationValidator.enforce() resolves known exit scenario_ids against populated registry
  - Adversarial fixture: unknown exit scenario → CitationViolation
  - Mentor narrative framing uses approved phrasing (CONTEXT.md specifics)
  - Backward-compat: stop scenario citations still resolve with exit registry present (RG-3)

RG-3 coverage (exit scenario golden citation tests).
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

_FOUR_EXIT_SCENARIO_IDS = [
    "counterfactual.exit.partial_1r",
    "counterfactual.exit.be_after_1r",
    "counterfactual.exit.trailing_atr",
    "counterfactual.exit.mfe_aware_trail",
]

_FIVE_STOP_SCENARIO_IDS = [
    "counterfactual.stop.atr_0_5",
    "counterfactual.stop.atr_1_0",
    "counterfactual.stop.atr_1_5",
    "counterfactual.stop.liquidity_buffer",
    "counterfactual.stop.session_range",
]

_ALL_NINE_SCENARIO_IDS = _FIVE_STOP_SCENARIO_IDS + _FOUR_EXIT_SCENARIO_IDS

_COUNTERFACTUAL_FIELDS = [
    "hypothetical_r",
    "hypothetical_exit_timestamp",
    "hypothetical_exit_price",
    "hypothetical_mae_r",
    "hypothetical_mfe_r",
    "divergence_frame_id",
    "explanation_summary",
]


def _make_registry_with_all_nine() -> Path:
    """Create a temporary registry dir with all 9 canonical scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _ALL_NINE_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
        )
    return tmpdir


def _make_registry_with_exit_only() -> Path:
    """Create a temporary registry dir with only the 4 exit scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _FOUR_EXIT_SCENARIO_IDS:
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


def _try_import_narrative_contracts():
    """Return (NarrativeEnvelope, NarrativeSentence, SentenceClass) or skip."""
    try:
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass

        return NarrativeEnvelope, NarrativeSentence, SentenceClass
    except ImportError:
        pytest.skip("fingpt_core narrative contracts not available")


def _make_assertion_envelope(
    citation_text: str, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
):
    """Build a NarrativeEnvelope with one ASSERTION sentence containing the citation."""
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
# Grammar tests (parse_citation_tokens — no registry needed)
# ---------------------------------------------------------------------------


def test_all_four_exit_scenario_citation_forms_parse():
    """All 4 exit scenario citations parse syntactically (RG-3).

    Grammar: [ref:counterfactual:<scenario_id>:<outcome_field>]
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    for scenario_id in _FOUR_EXIT_SCENARIO_IDS:
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


def test_exit_scenario_hypothetical_exit_timestamp_parses():
    """[ref:counterfactual:counterfactual.exit.trailing_atr:hypothetical_exit_timestamp] parses.

    This is the key citation from 61-03 PLAN.md must_haves:
    "Mentor narrative can cite exit-scenario hypothetical exit timestamp."
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    citation = "[ref:counterfactual:counterfactual.exit.trailing_atr:hypothetical_exit_timestamp]"
    tokens = parse_citation_tokens(citation)
    assert len(tokens) == 1, f"Expected 1 token, got {len(tokens)}: {tokens}"
    assert tokens[0].registry_id == "counterfactual"
    assert "hypothetical_exit_timestamp" in tokens[0].field


def test_all_exit_fields_parse_correctly():
    """All 7 counterfactual outcome fields parse for exit.trailing_atr scenario."""
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    scenario_id = "counterfactual.exit.trailing_atr"
    for field in _COUNTERFACTUAL_FIELDS:
        citation = f"[ref:counterfactual:{scenario_id}:{field}]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}"
        )
        assert tokens[0].field == f"{scenario_id}:{field}", (
            f"field mismatch: expected '{scenario_id}:{field}', got {tokens[0].field!r}"
        )


def test_all_nine_citation_forms_parse():
    """All 9 canonical scenario citations (stop + exit) parse syntactically.

    Cumulative backward-compat check: 61-03 didn't break 61-02 citation grammar.
    """
    parse_citation_tokens, _, _ = _try_import_citation_tools()

    for scenario_id in _ALL_NINE_SCENARIO_IDS:
        citation = f"[ref:counterfactual:{scenario_id}:hypothetical_r]"
        tokens = parse_citation_tokens(citation)
        assert len(tokens) == 1, (
            f"Expected 1 token for {citation!r}, got {len(tokens)}"
        )


# ---------------------------------------------------------------------------
# Validator tests (CitationValidator.enforce() — registry lookup)
# ---------------------------------------------------------------------------


def test_validator_resolves_trailing_atr_hypothetical_exit_timestamp():
    """CitationValidator.enforce() passes trailing_atr:hypothetical_exit_timestamp.

    This is the primary Phase 61-03 golden citation test — must_haves requirement.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "At the time of exit, the counterfactual.exit.trailing_atr policy would not yet have "
        "exited [ref:counterfactual:counterfactual.exit.trailing_atr:hypothetical_exit_timestamp]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass trailing_atr:hypothetical_exit_timestamp citation. "
            f"Got violation: {exc}"
        )


def test_validator_resolves_partial_1r_hypothetical_r():
    """CitationValidator.enforce() passes partial_1r:hypothetical_r."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under counterfactual exit policy, "
        "half the position would have realized 1R "
        "[ref:counterfactual:counterfactual.exit.partial_1r:hypothetical_r]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass partial_1r:hypothetical_r citation. "
            f"Got violation: {exc}"
        )


def test_validator_resolves_be_after_1r_hypothetical_r():
    """CitationValidator.enforce() passes be_after_1r:hypothetical_r."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under the break-even policy, MFE never crossed 1R; "
        "policy outcome class: never_activated "
        "[ref:counterfactual:counterfactual.exit.be_after_1r:hypothetical_r]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass be_after_1r:hypothetical_r citation. "
            f"Got violation: {exc}"
        )


def test_validator_resolves_mfe_aware_trail_explanation_summary():
    """CitationValidator.enforce() passes mfe_aware_trail:explanation_summary."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "The MFE trail policy peaks at MFE then gives back per the defined threshold "
        "[ref:counterfactual:counterfactual.exit.mfe_aware_trail:explanation_summary]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"CitationValidator should pass mfe_aware_trail:explanation_summary citation. "
            f"Got violation: {exc}"
        )


def test_adversarial_nonexistent_exit_policy_raises_violation():
    """Unknown exit scenario_id → CitationViolation (adversarial fixture, RG-3).

    Enforces that CitationValidator.enforce() hard-fails on unregistered scenario_ids.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    citation_text = (
        "Under the nonexistent exit policy "
        "[ref:counterfactual:counterfactual.exit.nonexistent_policy:hypothetical_r]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    with pytest.raises(CitationViolation):
        validator.enforce(envelope)


def test_backward_compat_stop_citations_resolve_with_all_nine():
    """61-02 stop scenario citations still resolve when all 9 YAMLs are present.

    RG-3: adding exit YAMLs must not break stop citation resolution.
    """
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_all_nine()
    validator = CitationValidator(registry_root)

    # From 61-02: primary golden citation
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
        pytest.fail(
            f"61-02 stop citation broke after 61-03 registry expansion: {exc}"
        )


def test_artifact_level_citation_passes_without_registry_lookup():
    """Artifact-level citation [ref:counterfactual:cf_<uuid>] passes without registry lookup."""
    parse_citation_tokens, CitationValidator, CitationViolation = _try_import_citation_tools()
    NarrativeEnvelope, NarrativeSentence, SentenceClass = _try_import_narrative_contracts()

    registry_root = _make_registry_with_exit_only()
    validator = CitationValidator(registry_root)

    # Approved phrasing from CONTEXT.md specifics section (artifact-level citation)
    citation_text = (
        "At the time of exit, the counterfactual.exit.trailing_atr policy would not yet have "
        "exited [ref:counterfactual:cf_550e8400e29b41d4a716446655440000]."
    )
    envelope = _make_assertion_envelope(
        citation_text, parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"Artifact-level cf_ citation should not require registry lookup. "
            f"Got violation: {exc}"
        )


def test_banned_phrases_not_in_approved_exit_narratives():
    """Law #10 guard: mentor narrative must NOT contain banned phrasing patterns.

    From CONTEXT.md specifics: banned = certainty / optimization / should-have claims.
    """
    banned_phrases = [
        "you should have held",
        "you should have exited",
        "the better exit was",
        "would definitely have",
        "would certainly have",
        "should have known",
        "optimal exit",
    ]

    approved_narratives = [
        (
            "At the time of exit, the counterfactual.exit.trailing_atr policy would not yet have "
            "exited [ref:counterfactual:counterfactual.exit.trailing_atr:hypothetical_exit_timestamp]."
        ),
        (
            "Under deterministic policy counterfactual.exit.partial_1r, using only information "
            "visible at the exit frame, the resulting branch captured 0.5R on the partial leg."
        ),
        (
            "The counterfactual.exit.be_after_1r policy was never_activated: MFE did not "
            "cross 1R during this execution."
        ),
    ]

    for narrative in approved_narratives:
        for banned in banned_phrases:
            assert banned.lower() not in narrative.lower(), (
                f"Approved narrative contains banned phrase {banned!r}:\n{narrative}"
            )
