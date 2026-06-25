"""Phase 92 Plan 03 — end-to-end classification pipeline tests.

The ``ResearchClassificationAgent`` orchestrates:
1. ``tier_classifier.classify_tier(source_id, acquisition_stream)``
2. ``indicator_linker.link_indicators(doc_text, doc_title)``
3. ``asset_linker.link_assets([indicator_id, ...])``
4. Status rule (Pitfall 3 soft-reject): indicators=[] → status='unlinked'

Plan-quote: "test_classification_pipeline_e2e.py: ResearchDocument input →
tier_classifier → indicator_linker → asset_linker → final {tier, indicators[],
assets[], status}; rejects with status='unlinked' when linker returns ∅".
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def test_e2e_fed_press_release_yields_classified_with_indicators():
    from agents.research.classification_agent import ResearchClassificationAgent

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text=(
            "Inflation has eased over the past year but remains elevated. "
            "The unemployment rate has remained low; nonfarm payrolls continued to expand."
        ),
        doc_title="FOMC Statement",
        acquisition_stream="B",
        source_id="fed_press_all",
    )
    assert result.status == "classified", f"Expected classified; got {result.status}"
    assert result.tier == 1, f"fed_* → tier 1; got {result.tier}"
    assert "CPIAUCSL" in result.indicators
    assert "UNRATE" in result.indicators
    assert "PAYEMS" in result.indicators
    assert result.reject_reason is None


def test_e2e_doc_with_no_indicator_mention_lands_in_unlinked(monkeypatch):
    """Pitfall 3 fix: doc with NO indicator link MUST land in status='unlinked'
    (NOT silently dropped, NOT blocking)."""
    from agents.research import indicator_linker
    from agents.research.classification_agent import ResearchClassificationAgent

    monkeypatch.setattr(indicator_linker, "_llm_classify_fallback", lambda *a, **kw: [])

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text="Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        doc_title="A paper about nothing",
        acquisition_stream="C",
        source_id="nber_papers",
    )
    assert result.status == "unlinked", f"Expected status='unlinked'; got {result.status!r}"
    assert result.reject_reason == "no_indicator_link", (
        f"Expected reject_reason='no_indicator_link'; got {result.reject_reason!r}"
    )
    assert result.indicators == []
    assert result.assets == []


def test_e2e_nber_paper_tier_is_3():
    from agents.research.classification_agent import ResearchClassificationAgent

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text="We study the relationship between unemployment and wage growth.",
        doc_title="NBER WP 32100",
        acquisition_stream="C",
        source_id="nber_papers",
    )
    assert result.tier == 3, f"nber_* → tier 3; got {result.tier}"


def test_e2e_manual_upload_tier_is_5():
    from agents.research.classification_agent import ResearchClassificationAgent

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text="My personal notes on CPI inflation dynamics.",
        doc_title="Personal notes",
        acquisition_stream="D",
        source_id="manual_upload",
    )
    assert result.tier == 5, f"Stream D (manual) → tier 5; got {result.tier}"


def test_e2e_classifications_dict_includes_linker_stage_and_tier_confidence():
    from agents.research.classification_agent import ResearchClassificationAgent

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text="The unemployment rate has remained low.",
        doc_title="Job Market Report",
        acquisition_stream="B",
        source_id="fed_press_all",
    )
    assert "linker_stage" in result.classifications
    assert "tier_confidence" in result.classifications
    assert result.classifications["linker_stage"] == "synonym"
    assert 0.0 <= result.classifications["tier_confidence"] <= 1.0


def test_e2e_assets_populated_when_indicators_have_drivers():
    from agents.research.classification_agent import ResearchClassificationAgent

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text="CPI inflation rose 3 percent. The 10-year Treasury yield ticked up.",
        doc_title="Macro Snapshot",
        acquisition_stream="B",
        source_id="fed_press_all",
    )
    assert result.status == "classified"
    asset_ids = set(result.assets)
    assert "UST10Y" in asset_ids, f"UST10Y should be linked via CPI+DGS10; got {asset_ids}"
    assert "GOLD" in asset_ids or "DXY" in asset_ids
