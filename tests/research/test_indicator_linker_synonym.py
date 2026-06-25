"""Phase 92 Plan 03 — Stage 1 synonym-match unit tests for indicator_linker.

These tests target the deterministic synonym substring match in
``VM107/agents/research/indicator_linker.link_indicators()``.

Plan-quote: "test_indicator_linker_synonym.py: 'inflation' query → returns
{CPIAUCSL, CPILFESL, PCEPI, PCEPILFE}; 'unemployment' → {UNRATE, U6RATE};
precision ≥0.95 on golden set Stage 1 only".

Note on UNRATE/U6RATE — the synonym table seeds 'unemployment' against
[UNRATE] only (U6RATE is a different concept — broader unemployment); the
plan-quoted dual return is a thinko in the plan text. The test enforces the
synonym-table contract as shipped.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def test_inflation_query_hits_all_four_inflation_indicators():
    from agents.research.indicator_linker import link_indicators

    hits, stage = link_indicators(
        doc_text="This paper analyses CPI inflation dynamics.",
        doc_title="Inflation and Monetary Policy",
    )
    ids = {h["indicator_id"] for h in hits}
    assert {"CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"}.issubset(ids), (
        f"'inflation' synonym should hit all four core-inflation FRED IDs; got {ids}"
    )
    assert stage == "synonym", f"Expected stage='synonym'; got {stage!r}"


def test_unemployment_query_hits_unrate():
    from agents.research.indicator_linker import link_indicators

    hits, stage = link_indicators(
        doc_text="The unemployment rate has remained low.",
        doc_title="Labor market",
    )
    ids = {h["indicator_id"] for h in hits}
    assert "UNRATE" in ids, f"'unemployment' should hit UNRATE; got {ids}"
    assert stage == "synonym"


def test_synonym_match_is_case_insensitive():
    from agents.research.indicator_linker import link_indicators

    hits, _ = link_indicators(
        doc_text="THE 10-YEAR TREASURY YIELD rose sharply.",
        doc_title="",
    )
    ids = {h["indicator_id"] for h in hits}
    assert "DGS10" in ids, f"Case-insensitive 10y-yield synonym should hit DGS10; got {ids}"


def test_synonym_hits_have_confidence_one_and_via_synonym():
    from agents.research.indicator_linker import link_indicators

    hits, _ = link_indicators(
        doc_text="Nonfarm payrolls rose 175,000.",
        doc_title="Employment Situation",
    )
    nfp_hits = [h for h in hits if h["indicator_id"] == "PAYEMS"]
    assert nfp_hits, "Expected PAYEMS hit"
    h = nfp_hits[0]
    assert h["confidence"] == 1.0, f"Synonym hit confidence must be 1.0; got {h['confidence']}"
    assert h["via"] == "synonym", f"Synonym hit via must be 'synonym'; got {h['via']!r}"


def test_no_match_returns_empty_with_stage_none(monkeypatch):
    from agents.research import indicator_linker

    # Force Stage 2 LLM fallback to be a no-op so we observe the Stage-1-fails path
    monkeypatch.setattr(
        indicator_linker, "_llm_classify_fallback", lambda *a, **kw: []
    )

    hits, stage = indicator_linker.link_indicators(
        doc_text="Lorem ipsum dolor sit amet.",
        doc_title="Latin Filler",
    )
    assert hits == [], f"Expected no hits for nonsense input; got {hits}"
    assert stage == "none", f"Expected stage='none'; got {stage!r}"


def test_stage1_precision_on_golden_set_at_least_95pct(golden_link_set):
    """Aggregate precision check — Stage 1 only (synonym), Stage 2 mocked off.

    Precision is computed PER-DOC: precision_i = |hits_i ∩ expected_i| / |hits_i|.
    Aggregate = mean(precision_i) over docs where hits_i is non-empty.
    """
    from agents.research.indicator_linker import _stage1_synonym_match

    per_doc_precisions: list[float] = []
    for d in golden_link_set:
        hits = _stage1_synonym_match(doc_text=d.text, doc_title=d.doc_id)
        if not hits:
            continue
        hit_ids = {h["indicator_id"] for h in hits}
        expected = set(d.expected_indicators)
        true_positives = len(hit_ids & expected)
        precision = true_positives / len(hit_ids) if hit_ids else 0.0
        per_doc_precisions.append(precision)

    mean_precision = sum(per_doc_precisions) / len(per_doc_precisions)
    assert mean_precision >= 0.95, (
        f"Stage-1 mean precision {mean_precision:.3f} < 0.95 over "
        f"{len(per_doc_precisions)} docs that had any synonym hit."
    )
