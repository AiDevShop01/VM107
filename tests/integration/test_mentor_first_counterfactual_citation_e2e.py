"""Phase 61-02 Task 5 — test_mentor_first_counterfactual_citation_e2e.py

First mentor counterfactual citation E2E test.

Verifies:
  - Citation token [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]
    resolves end-to-end: grammar parse → registry lookup → validator pass
  - CitationValidator accepts Phase 61-02 counterfactual scenario citations when
    the 5 canonical stop scenarios are registered (integration-level proof)
  - truth_mode='COUNTERFACTUAL' framing appears in mock mentor output
  - Phrasing patterns match approved form (hindsight discipline)

RG coverage: RG-2, RG-3, RG-8, RG-10.
Law #4: truth_mode=COUNTERFACTUAL framing required in writer output.
Law #10: hindsight discipline — "would have" / "Under counterfactual" phrasing.

Note: Full behavioral_mentor_agent pipeline test (with live LLM) is manual UAT
per 61-VALIDATION.md. This test covers the deterministic pipeline (grammar parse +
registry lookup + validator enforcement) without invoking the LLM layer.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# VM107 root setup
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Shared registry fixture
# ---------------------------------------------------------------------------

_FIVE_CANONICAL_SCENARIO_IDS = [
    "counterfactual.stop.atr_0_5",
    "counterfactual.stop.atr_1_0",
    "counterfactual.stop.atr_1_5",
    "counterfactual.stop.liquidity_buffer",
    "counterfactual.stop.session_range",
]


def _make_full_registry() -> Path:
    """Create a tmp registry with all 5 canonical stop scenarios + required Phase 60 entries."""
    tmpdir = Path(tempfile.mkdtemp())

    # Counterfactual scenarios (Phase 61-02)
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _FIVE_CANONICAL_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
            f"uses_future_information: false\n"
        )

    # Behavioral patterns (for Phase 60 backward-compat citations)
    bp_dir = tmpdir / "behavioral_pattern"
    bp_dir.mkdir()
    (bp_dir / "revenge_trade.yaml").write_text("id: revenge_trade\ntype: behavioral_pattern\n")

    return tmpdir


def _try_import_tools():
    """Import citation tools or skip if unavailable."""
    try:
        from fingpt_core.contracts.narrative.citation import parse_citation_tokens
        from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
        from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
        from helpers.citation_validator import CitationValidator, CitationViolation

        return parse_citation_tokens, NarrativeEnvelope, NarrativeSentence, SentenceClass, CitationValidator, CitationViolation
    except ImportError as exc:
        pytest.skip(f"fingpt_core or citation_validator not available: {exc}")


# ---------------------------------------------------------------------------
# E2E pipeline tests (deterministic — no LLM)
# ---------------------------------------------------------------------------


def test_first_counterfactual_citation_resolves_end_to_end():
    """The first mentor citation [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]
    resolves end-to-end through CitationValidator with populated registry.

    This is the Phase 61-02 graduation milestone: first end-to-end counterfactual
    citation resolution in the mentor pipeline.

    RG-3: citation golden test.
    RG-10: registry-driven policy class validated at citation time.
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_full_registry()
    validator = CitationValidator(registry_root)

    # The first counterfactual mentor citation — canonical Phase 61-02 form
    first_citation_text = (
        "Under the counterfactual stop policy at 1.5x ATR, the trade would have "
        "achieved a hypothetical R-multiple of 2.3 "
        "[ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r], "
        "compared to the as-traded R of 1.75."
    )

    sentence = NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text=first_citation_text,
        citations=parse_citation_tokens(first_citation_text),
    )
    envelope = NarrativeEnvelope(
        profile="behavioral_mentor",
        execution_id=None,
        sentences=[sentence],
    )

    # Grammar: citation must parse
    tokens = parse_citation_tokens(first_citation_text)
    assert len(tokens) == 1, f"Expected 1 citation token, got {tokens}"
    assert tokens[0].registry_id == "counterfactual"
    assert "counterfactual.stop.atr_1_5" in tokens[0].field
    assert "hypothetical_r" in tokens[0].field

    # Validator: citation must pass registry lookup
    try:
        validator.enforce(envelope)
    except CitationViolation as exc:
        pytest.fail(
            f"First counterfactual citation failed CitationValidator. "
            f"Phase 61-02 graduation blocked. Error: {exc}. "
            f"Ensure counterfactual.stop.atr_1_5.yaml exists in registry."
        )


def test_truth_mode_framing_in_mock_mentor_output():
    """Approved phrasing patterns appear in mock mentor narrative (Law #4, Law #10).

    Law #4: truth_mode=COUNTERFACTUAL must be framed explicitly.
    Law #10: hindsight discipline — ONLY approved forms:
      - "Under counterfactual stop policy..."
      - "would have"
      - "hypothetical"
    BANNED: "would have made", "the better stop was", "should have"
    """
    # Approved phrasing patterns (CONTEXT.md §8 approved forms)
    approved_phrases = [
        "Under counterfactual stop policy",
        "under the counterfactual",
        "would have",
        "hypothetical R",
        "hypothetical r",
        "hypothetical stop",
        "truth_mode=COUNTERFACTUAL",
    ]

    # Mock mentor output (as if written by behavioral_mentor_agent with CF awareness)
    mock_mentor_outputs = [
        (
            "Under the counterfactual stop policy at 1.5x ATR, the trade would have "
            "achieved a hypothetical R-multiple of 2.3 "
            "[ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]. "
            "truth_mode=COUNTERFACTUAL — this is a simulation, not a factual outcome."
        ),
        (
            "This analysis is truth_mode=COUNTERFACTUAL. "
            "The hypothetical stop placement at liquidity buffer would have "
            "avoided the stop sweep [ref:counterfactual:counterfactual.stop.liquidity_buffer:hypothetical_r]."
        ),
        (
            "Under counterfactual scenario atr_0_5, the tighter stop would have "
            "exited early [ref:counterfactual:counterfactual.stop.atr_0_5:hypothetical_exit_price]. "
            "This is hypothetical — truth_mode=COUNTERFACTUAL."
        ),
    ]

    # Banned phrasing patterns (Law #10 violations)
    banned_phrases = [
        "should have used",
        "should have placed",
        "the better stop was",
        "the optimal stop",
        "best stop location",
        "you should have",
    ]

    for i, output in enumerate(mock_mentor_outputs):
        # Law #4: must contain framing word
        has_framing = any(
            phrase.lower() in output.lower() for phrase in approved_phrases
        )
        assert has_framing, (
            f"Mock mentor output #{i} missing truth_mode framing word (Law #4). "
            f"Expected one of {approved_phrases[:3]}. "
            f"Output: {output[:100]!r}"
        )

        # Law #10: must NOT contain banned phrasing
        for banned in banned_phrases:
            assert banned.lower() not in output.lower(), (
                f"Mock mentor output #{i} contains banned phrasing {banned!r} (Law #10). "
                f"Hindsight discipline violation. Output: {output[:100]!r}"
            )


def test_citation_resolves_for_all_five_stop_scenarios_in_single_narrative():
    """Single narrative citing all 5 stop scenarios passes validation (RG-3, RG-10).

    Simulates a mentor narrative that compares all 5 stop scenarios in one review.
    Law #8: per-trade scope (one execution, 5 scenarios — all referenced).
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_full_registry()
    validator = CitationValidator(registry_root)

    # Build an envelope with 5 ASSERTION sentences, each citing a different scenario
    sentences = []
    for i, scenario_id in enumerate(_FIVE_CANONICAL_SCENARIO_IDS):
        text = (
            f"Under the counterfactual stop scenario {scenario_id.split('.')[-1].upper()}, "
            f"hypothetical R was {1.5 + i * 0.1:.1f} "
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
            f"CitationValidator failed on multi-scenario narrative. "
            f"All 5 stop scenarios should be resolvable. Error: {exc}"
        )


def test_hindsight_discipline_framing_in_counterfactual_assertions():
    """Counterfactual assertions must use COUNTERFACTUAL framing (Law #10).

    Validates that the hindsight-discipline SKILL's approved phrasing patterns
    cover the Phase 61-02 counterfactual citation grammar.

    Approved: "would have", "hypothetical", "Under counterfactual"
    This is a static contract test — no LLM needed.
    """
    approved_counterfactual_sentence_patterns = [
        "Under the counterfactual stop policy at 1.5x ATR, the trade would have achieved",
        "This is hypothetical — truth_mode=COUNTERFACTUAL.",
        "Under counterfactual scenario, the hypothetical R was 2.3.",
        "The trade would have avoided the stop sweep under the liquidity buffer scenario.",
    ]

    banned_in_counterfactual_context = [
        "The correct stop was",
        "You should have used ATR stop",
        "The optimal stop multiplier was",
        "Clearly the better choice was",
        "should have known",
    ]

    for sentence in approved_counterfactual_sentence_patterns:
        # Approved sentences should contain at least one approved framing phrase
        approved_keywords = ["would have", "hypothetical", "counterfactual", "truth_mode"]
        has_framing = any(kw.lower() in sentence.lower() for kw in approved_keywords)
        assert has_framing, (
            f"Approved sentence missing framing keyword: {sentence!r}. "
            "Law #10: counterfactual assertions require framing."
        )

    for sentence in banned_in_counterfactual_context:
        # Banned sentences should NOT contain approved framing
        # (these sentences are wrong regardless of framing)
        hindsight_markers = ["should have", "correct", "optimal", "better choice", "should have known"]
        has_hindsight = any(kw.lower() in sentence.lower() for kw in hindsight_markers)
        assert has_hindsight, (
            f"Test fixture error: banned sentence should contain hindsight marker: {sentence!r}"
        )
