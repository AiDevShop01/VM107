"""Phase 92 Plan 03 — combined Stage1+Stage2 precision/recall harness.

Plan-quote: "test_indicator_linker_precision_recall.py: runs Stage1+Stage2 over
all 30 docs, asserts precision ≥0.95 AND recall ≥0.80 against labels.yaml".

Precision = TP / (TP + FP)  — measured per-doc, then averaged across docs with
                              at least one hit.
Recall    = TP / (TP + FN)  — measured per-doc, then averaged across all docs.

Stage 2 is mocked with a "smart-enough" LLM stub: when the doc title or first
300 chars mention 'r-star', 'neutral rate', 'term premium', 'convenience yield',
or 'real yield', the stub returns [DGS10 @ 0.80]; otherwise [].
This mirrors the kind of judgment a real LLM is expected to make for the 5
LLM-fallback-only docs in the golden set.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def _smart_llm_stub(doc_text: str, doc_title: str, candidate_indicators):
    """A minimally-intelligent LLM stub that picks DGS10 for r-star/term-premium docs."""
    blob = (doc_title + " " + doc_text[:600]).lower()
    triggers = (
        "r-star",
        "r star",
        "neutral rate",
        "neutral interest rate",
        "natural rate",
        "term premium",
        "convenience yield",
        "real yield",
        "long-end yields",
        "long-term policy stance",
    )
    if any(t in blob for t in triggers):
        return [{"indicator_id": "DGS10", "confidence": 0.80}]
    return []


def _evaluate(golden_link_set, monkeypatch):
    from agents.research import indicator_linker

    monkeypatch.setattr(indicator_linker, "_llm_classify_fallback", _smart_llm_stub)

    per_doc_precision: list[float] = []
    per_doc_recall: list[float] = []
    for d in golden_link_set:
        hits, _stage = indicator_linker.link_indicators(
            doc_text=d.text, doc_title=d.doc_id
        )
        hit_ids = {h["indicator_id"] for h in hits}
        expected = set(d.expected_indicators)
        tp = len(hit_ids & expected)
        fp = len(hit_ids - expected)
        fn = len(expected - hit_ids)

        if hit_ids:
            per_doc_precision.append(tp / (tp + fp))
        per_doc_recall.append(tp / (tp + fn) if (tp + fn) > 0 else 1.0)

    mean_precision = sum(per_doc_precision) / len(per_doc_precision)
    mean_recall = sum(per_doc_recall) / len(per_doc_recall)
    return mean_precision, mean_recall


def test_combined_precision_at_least_0_95(golden_link_set, monkeypatch):
    precision, _recall = _evaluate(golden_link_set, monkeypatch)
    assert precision >= 0.95, (
        f"Combined Stage1+Stage2 precision {precision:.3f} < 0.95 on 30-doc golden set."
    )


def test_combined_recall_at_least_0_80(golden_link_set, monkeypatch):
    _precision, recall = _evaluate(golden_link_set, monkeypatch)
    assert recall >= 0.80, (
        f"Combined Stage1+Stage2 recall {recall:.3f} < 0.80 on 30-doc golden set."
    )
