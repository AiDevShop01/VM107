"""Phase 94-06 — Chief Economist Synthesizer graceful degradation tests (§J)."""

from __future__ import annotations

from agents.chief_economist_synthesizer import ChiefEconomistSynthesizer
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _ok(agent: str = "growth_analyst") -> SpecialistResponse:
    return SpecialistResponse(
        answer=f"{agent} answer — growth is positive with broad participation across the basket.",
        confidence=0.85,
        citations=["ref:indicator:GDP"],
        evidence=[{"indicator_id": "GDP", "role": "primary"}],
        limitations=[],
        related_entities=["pillar:Growth"],
    )


def _errored(agent: str = "forecast_agent") -> SpecialistResponse:
    """SpecialistResponse with confidence=0 sentinel — treated as ERROR by synthesizer."""
    return SpecialistResponse(
        answer="forecast unavailable",
        confidence=0.0,
        citations=[],
        evidence=[],
        limitations=["forecast feed timeout"],
        related_entities=[],
    )


def test_degraded_specialist_not_fatal():
    """One specialist returns confidence=0 — synthesizer still produces an answer."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_ok("growth_analyst"), _errored("forecast_agent"), _ok("inflation_analyst")],
        query="What's going on?",
        specialist_ids=["growth_analyst", "forecast_agent", "inflation_analyst"],
    )
    # Answer composed from the two healthy specialists.
    assert out["answer"]
    assert "growth_analyst" in out["answer"] or "growth" in out["answer"].lower()
    # Errored specialist surfaces as an explicit limitation note.
    assert any(
        "forecast_agent" in lim and "unavailable" in lim.lower()
        for lim in out["limitations"]
    ), f"errored specialist must be noted in limitations; got: {out['limitations']}"


def test_all_specialists_errored_returns_no_answer():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_errored("a"), _errored("b")],
        query="why",
        specialist_ids=["a", "b"],
    )
    assert "No specialists were available" in out["answer"]
    assert out["confidence"] == 0.0
    # Both errored specialists noted.
    assert any("a unavailable" in lim for lim in out["limitations"])
    assert any("b unavailable" in lim for lim in out["limitations"])


def test_degraded_confidence_excludes_errored_weight():
    """Citation-weighted confidence ignores errored specialists."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_ok("good"), _errored("bad")],
        query="why",
        specialist_ids=["good", "bad"],
    )
    # Only the healthy specialist (confidence 0.85, 1 citation) counts.
    assert abs(out["confidence"] - 0.85) < 0.01


def test_per_paragraph_attribution_skips_errored():
    """Errored specialists do NOT appear in paragraph attribution map."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_ok("good"), _errored("bad")],
        query="why",
        specialist_ids=["good", "bad"],
    )
    attribution = out["_paragraph_attribution"]
    assert "bad" not in attribution.values()
    assert "good" in attribution.values()
