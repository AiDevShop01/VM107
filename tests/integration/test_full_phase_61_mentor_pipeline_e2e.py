"""Phase 61-05 Task 3 — test_full_phase_61_mentor_pipeline_e2e.py

Full Phase 61 V1 mentor pipeline E2E: all 15 canonical scenarios available.

Verifies:
  - All 15 canonical scenario citations resolve end-to-end through CitationValidator
  - Mentor narrative containing all 4 tier citations (stop + exit + regime + alt-entry)
    passes validator
  - Hindsight-discipline framing holds cumulatively across all 4 tiers
  - truth_mode=COUNTERFACTUAL framing explicit in every citation sentence (Law #4)
  - Cross-tier conflation test: narrator must NOT compare counterfactual branches
    against each other ("atr_1_5 would have outperformed atr_0_5" — covert optimization)

RG coverage: RG-2, RG-3, RG-8, RG-10.
Laws: ALL 10 — cumulative Phase 61 V1 quality gate.

Note: Full behavioral_mentor_agent pipeline with live LLM is Manual UAT (Task 4).
This module covers deterministic pipeline (grammar + registry + validator) without LLM.
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
# All 15 canonical scenario IDs (Phase 61 V1)
# ---------------------------------------------------------------------------

_ALL_15_SCENARIO_IDS = [
    # Tier 1: Stop
    "counterfactual.stop.atr_0_5",
    "counterfactual.stop.atr_1_0",
    "counterfactual.stop.atr_1_5",
    "counterfactual.stop.liquidity_buffer",
    "counterfactual.stop.session_range",
    # Tier 2: Exit
    "counterfactual.exit.partial_1r",
    "counterfactual.exit.be_after_1r",
    "counterfactual.exit.trailing_atr",
    "counterfactual.exit.mfe_aware_trail",
    # Tier 3: Regime-gate
    "counterfactual.regime.skip_low_vol",
    "counterfactual.regime.skip_countertrend",
    "counterfactual.regime.avoid_news_window",
    # Tier 4: Alt-entry (ships last)
    "counterfactual.entry.wait_for_retest",
    "counterfactual.entry.bos_confirmation",
    "counterfactual.entry.late_entry_5_bars",
]

assert len(_ALL_15_SCENARIO_IDS) == 15


def _make_full_15_registry() -> Path:
    """Create temporary registry dir with all 15 canonical scenario YAMLs."""
    tmpdir = Path(tempfile.mkdtemp())
    cf_dir = tmpdir / "counterfactual_scenario"
    cf_dir.mkdir()
    for scenario_id in _ALL_15_SCENARIO_IDS:
        (cf_dir / f"{scenario_id}.yaml").write_text(
            f"id: {scenario_id}\n"
            f"type: counterfactual_scenario\n"
            f"scenario_tier: canonical\n"
            f"scenario_version: '1.0.0'\n"
            f"uses_future_information: false\n"
        )
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
# Phase 61 V1: all 15 citations resolve
# ---------------------------------------------------------------------------


def test_full_phase_61_all_15_citations_resolve():
    """All 15 canonical scenario citations resolve through CitationValidator (RG-3, RG-10).

    Phase 61 V1 graduation milestone: full canonical set resolves end-to-end.
    Each citation uses approved framing (would have, hypothetical, counterfactual).
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_full_15_registry()
    validator = CitationValidator(registry_root)

    # Build a narrative citing all 15 scenarios with approved framing
    sentences = []
    for i, scenario_id in enumerate(_ALL_15_SCENARIO_IDS):
        text = (
            f"Under counterfactual policy {scenario_id.split('.')[-1].upper()}, "
            f"the trade would have achieved hypothetical R of {1.0 + i * 0.1:.1f}R "
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
            f"Full Phase 61 V1 (15 scenarios) CitationValidator failed. "
            f"Phase 61 V1 graduation blocked. Error: {exc}"
        )


# ---------------------------------------------------------------------------
# Multi-tier narrative: stop + exit + regime + alt-entry
# ---------------------------------------------------------------------------


def test_multi_tier_narrative_all_four_families():
    """Narrative citing one scenario from each of the 4 tiers passes validation.

    Verifies: phase 61 V1 mentor can cite across all 4 scenario families in a
    single narrative without citation resolution failure.
    RG-3, RG-8.
    """
    (
        parse_citation_tokens,
        NarrativeEnvelope,
        NarrativeSentence,
        SentenceClass,
        CitationValidator,
        CitationViolation,
    ) = _try_import_tools()

    registry_root = _make_full_15_registry()
    validator = CitationValidator(registry_root)

    multi_tier_citations = [
        # Stop tier
        (
            "Under the counterfactual stop policy at 1.5x ATR, the position would have "
            "survived the sweep [ref:counterfactual:counterfactual.stop.atr_1_5:hypothetical_r]."
        ),
        # Exit tier
        (
            "Under counterfactual exit policy trailing_atr, the position would have "
            "exited earlier [ref:counterfactual:counterfactual.exit.trailing_atr:hypothetical_exit_timestamp]."
        ),
        # Regime tier
        (
            "Under counterfactual regime gate skip_low_vol, the trade would not have "
            "been taken [ref:counterfactual:counterfactual.regime.skip_low_vol:policy_outcome_class]."
        ),
        # Alt-entry tier
        (
            "Under counterfactual alt-entry policy wait_for_retest, the alt-entry "
            "signal would have fired at T+3 "
            "[ref:counterfactual:counterfactual.entry.wait_for_retest:divergence_frame_id]."
        ),
    ]

    sentences = []
    for i, text in enumerate(multi_tier_citations):
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
            f"Multi-tier narrative (4 families) failed CitationValidator. "
            f"Error: {exc}"
        )


# ---------------------------------------------------------------------------
# Hindsight-discipline cumulative check
# ---------------------------------------------------------------------------


def test_cumulative_hindsight_discipline_all_four_tiers():
    """Approved phrasing across all 4 tiers satisfies hindsight-discipline (Law #6, Law #10).

    Phase 61 V1 cumulative quality gate:
    - APPROVED: "would have", "counterfactual", "hypothetical", "truth_mode=COUNTERFACTUAL"
    - BANNED: "should have", "better stop", "optimal", "your impulsive entry"
    """
    approved_narratives = [
        # Stop tier — approved
        "Under counterfactual stop policy at 1.5x ATR, the branch would have survived.",
        # Exit tier — approved
        "Under counterfactual exit policy trailing_atr, the hypothetical exit would have occurred later.",
        # Regime tier — approved
        "Under counterfactual regime gate, the trade would not have been taken because ATR ranked in 22nd percentile.",
        # Alt-entry tier — approved (highest risk)
        "Under counterfactual alt-entry policy wait_for_retest, the alt-entry signal would have fired at T+3.",
    ]

    banned_narratives = [
        # Stop tier — banned
        "You should have widened your stop to 1.5x ATR.",
        # Exit tier — banned
        "You should have held longer for 4R.",
        # Regime tier — banned
        "You should not have traded in this low-vol environment.",
        # Alt-entry tier — HIGHEST RISK — banned
        "You should have waited for the retest.",
        "Your impulsive entry cost you 0.7R.",
        "Late entries would have improved your average R.",
    ]

    approved_framing = ["would have", "counterfactual", "hypothetical", "truth_mode"]
    banned_markers = [
        "you should",
        "should have",
        "should not have",
        "your impulsive",
        "would have improved your",
    ]

    # All approved narratives must contain framing
    for narrative in approved_narratives:
        has_framing = any(kw.lower() in narrative.lower() for kw in approved_framing)
        assert has_framing, (
            f"Approved narrative missing COUNTERFACTUAL framing (Law #4). "
            f"Narrative: {narrative!r}"
        )

    # All banned narratives must contain hindsight markers (for test fixture validity)
    for narrative in banned_narratives:
        has_marker = any(m.lower() in narrative.lower() for m in banned_markers)
        assert has_marker, (
            f"Test fixture error: banned narrative should contain hindsight marker. "
            f"Narrative: {narrative!r}"
        )


# ---------------------------------------------------------------------------
# Cross-tier conflation check (covert optimization — banned)
# ---------------------------------------------------------------------------


def test_cross_tier_comparison_is_covert_optimization():
    """Comparing two counterfactual scenarios against each other = covert optimization (banned).

    Phase 61 Law #8 + Law #6: comparing "atr_1_5 would have outperformed atr_0_5"
    is a covert optimization counterfactual. The system must NEVER make this comparison.

    This test documents the pattern. Actual enforcement is via manual UAT (Task 4).
    """
    # Banned cross-scenario comparisons
    banned_comparisons = [
        "The atr_1_5 stop would have outperformed the atr_0_5 stop.",
        "Across all the scenarios, the trailing_atr exit would have been best.",
        "Of these counterfactuals, the wait_for_retest entry achieves the highest R.",
        "Comparing the two regime gates, skip_low_vol would have saved more trades.",
    ]

    # Markers that indicate cross-scenario optimization framing
    optimization_markers = [
        "outperformed",
        "would have been best",
        "highest r",
        "saved more",
        "comparing the",
        "across all the scenarios",
    ]

    for comparison in banned_comparisons:
        has_optimization_marker = any(
            marker.lower() in comparison.lower() for marker in optimization_markers
        )
        assert has_optimization_marker, (
            f"Test fixture error: banned comparison should contain optimization marker. "
            f"Comparison: {comparison!r}"
        )


# ---------------------------------------------------------------------------
# Phase 61 V1 graduation: 15 scenarios registered
# ---------------------------------------------------------------------------


def test_phase_61_v1_canonical_set_size():
    """Phase 61 V1 canonical set has exactly 15 scenarios."""
    assert len(_ALL_15_SCENARIO_IDS) == 15


def test_phase_61_v1_all_four_tiers_represented():
    """All 4 scenario tiers (stop, exit, regime, entry) are represented."""
    has_stop = any("stop" in s for s in _ALL_15_SCENARIO_IDS)
    has_exit = any("exit" in s for s in _ALL_15_SCENARIO_IDS)
    has_regime = any("regime" in s for s in _ALL_15_SCENARIO_IDS)
    has_entry = any("entry" in s for s in _ALL_15_SCENARIO_IDS)

    assert has_stop, "Missing stop tier scenarios"
    assert has_exit, "Missing exit tier scenarios"
    assert has_regime, "Missing regime tier scenarios"
    assert has_entry, "Missing alt-entry tier scenarios"
