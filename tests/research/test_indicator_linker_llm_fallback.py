"""Phase 92 Plan 03 — Stage 2 LLM-fallback unit tests for indicator_linker.

Plan-quote: "test_indicator_linker_llm_fallback.py: when synonym returns ∅,
mock_llm_client.classify returns [{indicator_id: 'DGS10', confidence: 0.85}];
result accepted (≥0.7 threshold); when LLM confidence 0.5, rejected".
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def test_llm_fallback_accepts_high_confidence_hits(monkeypatch):
    from agents.research import indicator_linker

    monkeypatch.setattr(
        indicator_linker,
        "_llm_classify_fallback",
        lambda doc_text, doc_title, candidate_indicators: [
            {"indicator_id": "DGS10", "confidence": 0.85}
        ],
    )

    hits, stage = indicator_linker.link_indicators(
        doc_text="Lorem ipsum non-matching text.",
        doc_title="Some macro paper",
    )
    assert any(h["indicator_id"] == "DGS10" for h in hits), (
        f"Expected DGS10 hit from LLM fallback; got {hits}"
    )
    dgs10 = next(h for h in hits if h["indicator_id"] == "DGS10")
    assert dgs10["via"] == "llm"
    assert dgs10["confidence"] == 0.85
    assert stage == "llm"


def test_llm_fallback_rejects_below_threshold(monkeypatch):
    from agents.research import indicator_linker

    monkeypatch.setattr(
        indicator_linker,
        "_llm_classify_fallback",
        lambda doc_text, doc_title, candidate_indicators: [
            {"indicator_id": "DGS10", "confidence": 0.50}
        ],
    )

    hits, stage = indicator_linker.link_indicators(
        doc_text="Lorem ipsum non-matching text.",
        doc_title="Some macro paper",
    )
    assert not any(h["indicator_id"] == "DGS10" for h in hits), (
        f"DGS10 at confidence 0.5 should be REJECTED (<0.7 threshold); got {hits}"
    )
    assert stage == "none", f"Expected stage='none' when LLM hits fall below threshold; got {stage!r}"


def test_llm_fallback_only_called_when_stage1_empty(monkeypatch):
    """Stage 2 must NOT be invoked if Stage 1 returns hits."""
    from agents.research import indicator_linker

    sentinel = {"called": 0}

    def _spy(*args, **kwargs):
        sentinel["called"] += 1
        return []

    monkeypatch.setattr(indicator_linker, "_llm_classify_fallback", _spy)

    hits, stage = indicator_linker.link_indicators(
        doc_text="The unemployment rate has eased.",
        doc_title="FOMC press release",
    )
    assert stage == "synonym"
    assert sentinel["called"] == 0, (
        f"LLM fallback called {sentinel['called']} times even though Stage 1 hit."
    )


def test_llm_fallback_threshold_is_exclusive_at_0_7(monkeypatch):
    from agents.research import indicator_linker

    monkeypatch.setattr(
        indicator_linker,
        "_llm_classify_fallback",
        lambda *a, **kw: [
            {"indicator_id": "DGS10", "confidence": 0.70},
            {"indicator_id": "UNRATE", "confidence": 0.69},
        ],
    )

    hits, _ = indicator_linker.link_indicators(
        doc_text="Lorem ipsum.",
        doc_title="Filler",
    )
    ids = {h["indicator_id"] for h in hits}
    assert "DGS10" in ids, "0.70 confidence should be ACCEPTED (≥0.70 threshold)"
    assert "UNRATE" not in ids, "0.69 confidence should be REJECTED (<0.70)"


def test_llm_fallback_returns_no_hits_yields_stage_none(monkeypatch):
    from agents.research import indicator_linker

    monkeypatch.setattr(indicator_linker, "_llm_classify_fallback", lambda *a, **kw: [])

    hits, stage = indicator_linker.link_indicators(
        doc_text="Empty fallback case.",
        doc_title="Test",
    )
    assert hits == []
    assert stage == "none"
