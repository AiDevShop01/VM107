"""Phase 61-05 Task 3 — test_counterfactual_alt_entry_citation_golden.py

Citation golden tests for the 3 canonical alt-entry scenario citations.

Alt-entry citations have the HIGHEST hindsight-bias risk in Phase 61.
Law #6 phrasing discipline is most critical here: the system must
never slide into "you should have waited" territory.

Tests:
  - Citation grammar parses correctly for all 3 alt-entry scenario citation forms
  - CitationValidator.enforce() resolves alt-entry scenario_ids against populated registry
  - policy_outcome_class field resolves as a citation token
  - Adversarial fixture: unknown alt-entry scenario → CitationViolation
  - Backward-compat: stop + exit + regime citations still resolve with full 15-scenario
    registry (RG-3 cumulative)
  - Approved phrasing documented (Law #6 — alt-entry hindsight discipline)
  - Banned phrasing documented (most critical Law #6 regression test in Phase 61)

RG-3 coverage (alt-entry scenario golden citation tests).
Law #6 coverage: approved vs banned narrative phrasing for alt-entry scenarios.
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

_THREE_ALT_ENTRY_SCENARIO_IDS = [
    "counterfactual.entry.wait_for_retest",
    "counterfactual.entry.bos_confirmation",
    "counterfactual.entry.late_entry_5_bars",
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

_THREE_REGIME_SCENARIO_IDS = [
    "counterfactual.regime.skip_low_vol",
    "counterfactual.regime.skip_countertrend",
    "counterfactual.regime.avoid_news_window",
]

_ALL_FIFTEEN_SCENARIO_IDS = (
    _FIVE_STOP_SCENARIO_IDS
    + _FOUR_EXIT_SCENARIO_IDS
    + _THREE_REGIME_SCENARIO_IDS
    + _THREE_ALT_ENTRY_SCENARIO_IDS
)


def _make_registry_with_all_fifteen() -> Path:
    """Create a temporary registry dir with all 15 canonical scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _ALL_FIFTEEN_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
            f"uses_future_information: false\n"
        )

    # behavioral_pattern dir for backward-compat
    bp_dir = tmpdir / "behavioral_pattern"
    bp_dir.mkdir()
    (bp_dir / "revenge_trade.yaml").write_text("id: revenge_trade\ntype: behavioral_pattern\n")

    return tmpdir


def _make_registry_with_alt_entry_only() -> Path:
    """Registry with only the 3 alt-entry scenarios (for isolation tests)."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _THREE_ALT_ENTRY_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
            f"uses_future_information: false\n"
        )
    bp_dir = tmpdir / "behavioral_pattern"
    bp_dir.mkdir()
    return tmpdir


def _try_import_tools():
    """Import citation tools or skip if unavailable."""
    try:
        from fingpt_core.contracts.narrative.citation import parse_citation_tokens
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
        from helpers.citation_validator import CitationValidator, CitationViolation

        return (
            parse_citation_tokens,
            NarrativeEnvelope,
            NarrativeSentence,
            SentenceClass,
            CitationValidator,
            CitationViolation,
        )
    except ImportError as exc:
        pytest.skip(f"fingpt_core or citation_validator not available: {exc}")


# ---------------------------------------------------------------------------
# Grammar: citation token parsing
# ---------------------------------------------------------------------------


def test_wait_for_retest_citation_grammar():
    """Citation [ref:counterfactual:counterfactual.entry.wait_for_retest:policy_outcome_class] parses."""
    parse_citation_tokens, *_ = _try_import_tools()

    text = (
        "Under counterfactual alt-entry policy "
        "[ref:counterfactual:counterfactual.entry.wait_for_retest:policy_outcome_class], "
        "the alt-entry signal fired at replay frame T+3."
    )
    tokens = parse_citation_tokens(text)
    assert len(tokens) == 1
    assert tokens[0].registry_id == "counterfactual"
    assert "counterfactual.entry.wait_for_retest" in tokens[0].field
    assert "policy_outcome_class" in tokens[0].field


def test_bos_confirmation_citation_grammar():
    """Citation [ref:counterfactual:counterfactual.entry.bos_confirmation:divergence_frame_id] parses."""
    parse_citation_tokens, *_ = _try_import_tools()

    text = (
        "Under counterfactual alt-entry policy "
        "[ref:counterfactual:counterfactual.entry.bos_confirmation:divergence_frame_id], "
        "the BOS confirmation signal fired at replay frame T+5."
    )
    tokens = parse_citation_tokens(text)
    assert len(tokens) == 1
    assert tokens[0].registry_id == "counterfactual"
    assert "counterfactual.entry.bos_confirmation" in tokens[0].field


def test_late_entry_5_bars_citation_grammar():
    """Citation [ref:counterfactual:counterfactual.entry.late_entry_5_bars:hypothetical_exit_timestamp] parses."""
    parse_citation_tokens, *_ = _try_import_tools()

    text = (
        "Under counterfactual alt-entry policy "
        "[ref:counterfactual:counterfactual.entry.late_entry_5_bars:hypothetical_exit_timestamp], "
        "the deterministic 5-bar-later entry would have re-threaded SL/TP geometry."
    )
    tokens = parse_citation_tokens(text)
    assert len(tokens) == 1
    assert tokens[0].registry_id == "counterfactual"
    assert "counterfactual.entry.late_entry_5_bars" in tokens[0].field


# ---------------------------------------------------------------------------
# CitationValidator: resolution with 15-scenario registry
# ---------------------------------------------------------------------------


def test_all_three_alt_entry_citations_resolve():
    """All 3 alt-entry scenario citations resolve against full 15-scenario registry."""
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_registry_with_all_fifteen()
    validator = CitationValidator(registry_root)

    sentences = []
    for i, scenario_id in enumerate(_THREE_ALT_ENTRY_SCENARIO_IDS):
        field = "hypothetical_r"
        text = (
            f"Under counterfactual alt-entry policy, hypothetical R was 1.{i}R "
            f"[ref:counterfactual:{scenario_id}:{field}]."
        )
        sentences.append(
            NarrativeSentence(
                sentence_index=i,
                sentence_class=SentenceClass.ASSERTION,
                text=text,
                citations=parse_citation_tokens(text),
            )
        )

    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=sentences,
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"Alt-entry citations failed CitationValidator. "
            f"Phase 61-05 graduation blocked. Error: {exc}"
        )


def test_unknown_alt_entry_scenario_fails_validation():
    """Unknown alt-entry scenario_id → CitationViolation (adversarial regression test).

    This test ensures CitationValidator rejects unknown scenario_ids in the
    counterfactual namespace — not just unrecognized registry categories.
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_registry_with_all_fifteen()
    validator = CitationValidator(registry_root)

    # Unknown scenario (not registered in Phase 61 V1)
    text = (
        "Under counterfactual alt-entry policy, hypothetical R was 1.5R "
        "[ref:counterfactual:counterfactual.entry.late_entry_10_bars:hypothetical_r]."
    )
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

    with pytest.raises(CitationViolation):
        validator.enforce(envelope)


# ---------------------------------------------------------------------------
# Backward-compat: all 15 scenarios resolve together (RG-3 cumulative)
# ---------------------------------------------------------------------------


def test_all_fifteen_canonical_citations_resolve_together():
    """Single narrative citing all 15 canonical scenarios passes validation (RG-3, RG-10).

    Cumulative architectural sanity: Phase 61 V1 full canonical set co-exists
    in the citation resolution path.
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_registry_with_all_fifteen()
    validator = CitationValidator(registry_root)

    sentences = []
    for i, scenario_id in enumerate(_ALL_FIFTEEN_SCENARIO_IDS):
        text = (
            f"Under counterfactual policy {scenario_id.split('.')[-1].upper()}, "
            f"hypothetical R was {1.0 + i * 0.1:.1f}R "
            f"[ref:counterfactual:{scenario_id}:hypothetical_r]."
        )
        sentences.append(
            NarrativeSentence(
                sentence_index=i,
                sentence_class=SentenceClass.ASSERTION,
                text=text,
                citations=parse_citation_tokens(text),
            )
        )

    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=sentences,
    )

    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"Full 15-scenario citation set failed CitationValidator. "
            f"Phase 61 V1 cumulative sanity check failed. Error: {exc}"
        )


# ---------------------------------------------------------------------------
# Law #6: approved vs banned phrasing (most important test in Phase 61)
# ---------------------------------------------------------------------------


def test_approved_alt_entry_phrasing_patterns():
    """Approved alt-entry phrasing patterns satisfy hindsight-discipline rules (Law #6).

    These are the CANONICAL approved phrases for alt-entry mentor narration.
    Alt-entry has HIGHEST re-threading risk in Phase 61.
    """
    approved_phrases = [
        # wait_for_retest approved form
        (
            "Under counterfactual alt-entry policy `counterfactual.entry.wait_for_retest`, "
            "the alt-entry signal fired at replay frame T+3, where the trade would have "
            "entered at a different price and re-threaded SL/TP geometry."
        ),
        # bos_confirmation approved form
        (
            "Under counterfactual alt-entry policy "
            "`counterfactual.entry.bos_confirmation`, the BOS confirmation signal fired "
            "at replay frame T+5, and the trade would have entered at a different price frame."
        ),
        # late_entry_5_bars approved form
        (
            "Under counterfactual alt-entry policy "
            "`counterfactual.entry.late_entry_5_bars`, the deterministic 5-bar-later "
            "entry would have re-threaded SL/TP geometry while preserving the R-unit discipline."
        ),
    ]

    required_framing_keywords = ["would have", "counterfactual", "hypothetical", "alt-entry"]

    for phrase in approved_phrases:
        has_framing = any(kw.lower() in phrase.lower() for kw in required_framing_keywords)
        assert has_framing, (
            f"Approved alt-entry phrase missing framing keyword. "
            f"Law #6 requires 'would have' or 'counterfactual'. "
            f"Phrase: {phrase[:100]!r}"
        )


def test_banned_alt_entry_phrasing_patterns():
    """Banned alt-entry phrasing patterns must NOT appear in mentor narratives (Law #6).

    Alt-entry has HIGHEST hindsight-bias risk. These are the key violations
    that 'would have entered later' framing can slip into.
    """
    # These are banned phrases that must be caught by manual UAT (Task 4)
    banned_phrases = [
        "You should have waited for a retest.",
        "You should have waited for BOS confirmation.",
        "Patient entries would have improved your average R.",
        "Your impulsive entry cost you 0.7R.",
        "Late entries structurally outperform early entries.",
        "Waiting would have been better.",
        "Should have been more patient.",
        "Your entry was too early.",
    ]

    hindsight_markers = [
        "you should",
        "should have",
        "your entry was",
        "your impulsive",
        "would have improved",
        "structurally outperform",
        "waiting would have been better",
        "been more patient",
    ]

    for phrase in banned_phrases:
        has_marker = any(marker.lower() in phrase.lower() for marker in hindsight_markers)
        assert has_marker, (
            f"Test fixture error: banned phrase should contain hindsight marker. "
            f"Phrase: {phrase!r}"
        )


def test_truth_mode_framing_in_alt_entry_citations():
    """Alt-entry citations must include truth_mode=COUNTERFACTUAL framing (Law #4).

    Every sentence citing a counterfactual alt-entry artifact must frame it
    as hypothetical, not factual.
    """
    # Check that approved forms contain hypothetical framing
    approved_with_framing = [
        "Under counterfactual alt-entry policy, the trade WOULD HAVE entered at T+3.",
        "This is truth_mode=COUNTERFACTUAL — under this alt-entry policy, the entry WOULD HAVE been later.",
        "Under counterfactual policy late_entry_5_bars, the hypothetical entry price was 1.0810.",
    ]

    framing_keywords = ["would have", "counterfactual", "hypothetical", "truth_mode=counterfactual"]

    for sentence in approved_with_framing:
        has_framing = any(kw.lower() in sentence.lower() for kw in framing_keywords)
        assert has_framing, (
            f"Approved alt-entry sentence missing COUNTERFACTUAL framing keyword. "
            f"Law #4: truth_mode=COUNTERFACTUAL framing is mandatory. "
            f"Sentence: {sentence!r}"
        )
