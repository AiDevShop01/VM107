"""Phase 94-06 — Chief Economist Synthesizer §I locked response structure tests."""

from __future__ import annotations

from agents.chief_economist_synthesizer import ChiefEconomistSynthesizer
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _response(agent: str = "growth_analyst") -> SpecialistResponse:
    return SpecialistResponse(
        answer=(
            f"{agent.title()}: macro environment shows positive momentum across the "
            f"selected pillar; contributors point to broad-based participation."
        ),
        confidence=0.8,
        citations=[
            f"ref:indicator:{agent.upper()}_A",
            f"ref:indicator:{agent.upper()}_B",
            "ref:episode:ep-2026-04",
        ],
        evidence=[
            {"indicator_id": "X", "role": "contributor"},
            {"indicator_id": "Y", "role": "contributor"},
        ],
        limitations=[],
        related_entities=[f"pillar:{agent}", "country:US"],
    )


def test_response_follows_locked_structure():
    """§I — Answer / Evidence / Supporting Indicators / Research / Confidence /
    Alternative Views / Next Questions."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst"), _response("inflation_analyst")],
        query="What's going on?",
        specialist_ids=["growth_analyst", "inflation_analyst"],
    )
    required = {
        "answer",
        "evidence",
        "supporting_indicators",
        "research",
        "confidence",
        "alternative_views",
        "next_questions",
    }
    assert required <= set(out.keys()), f"missing §I keys: {required - set(out.keys())}"


def test_per_paragraph_attribution_present():
    """Each composed paragraph carries a `<!-- specialist:<id> -->` marker
    (or equivalent metadata field) for Phase 71 Evidence Drawer."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst"), _response("inflation_analyst")],
        query="why",
        specialist_ids=["growth_analyst", "inflation_analyst"],
    )
    assert "<!-- specialist:growth_analyst -->" in out["answer"]
    assert "<!-- specialist:inflation_analyst -->" in out["answer"]
    # Map form for frontend Evidence Drawer.
    attribution = out["_paragraph_attribution"]
    assert "p0" in attribution
    assert attribution["p0"] == "growth_analyst"
    assert attribution["p1"] == "inflation_analyst"


def test_indicators_extracted_from_citations():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst")],
        query="why",
        specialist_ids=["growth_analyst"],
    )
    assert "ref:indicator:GROWTH_ANALYST_A" in out["supporting_indicators"]


def test_research_extracted_from_citations():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst")],
        query="why",
        specialist_ids=["growth_analyst"],
    )
    assert any(c.startswith("ref:episode:") for c in out["research"])


def test_next_questions_pull_from_related_entities():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst")],
        query="why",
        specialist_ids=["growth_analyst"],
    )
    assert any("pillar:growth_analyst" in q for q in out["next_questions"])


def test_evidence_carries_specialist_attribution():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response("growth_analyst")],
        query="why",
        specialist_ids=["growth_analyst"],
    )
    assert all(ev["_specialist"] == "growth_analyst" for ev in out["evidence"])


def test_specialist_ids_length_mismatch_raises():
    """Safety guard — silently mis-attributing paragraphs is a §I violation."""
    import pytest

    synth = ChiefEconomistSynthesizer()
    with pytest.raises(ValueError):
        synth.synthesize(
            [_response("a"), _response("b")],
            query="why",
            specialist_ids=["a"],   # too short
        )
