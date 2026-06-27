"""Phase 94-06 — Chief Economist Synthesizer confidence weighting (Wave-0 RED → GREEN).

Locks per §J:
* Confidence is CITATION-WEIGHTED — specialists with more citations carry
  more weight than specialists with thin evidence.
* Simple arithmetic mean is forbidden (and tested for via numeric divergence).
"""

from __future__ import annotations

import pytest

from agents.chief_economist_synthesizer import ChiefEconomistSynthesizer
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _response(confidence: float, n_citations: int, agent: str = "x") -> SpecialistResponse:
    return SpecialistResponse(
        answer=f"{agent} narrative",
        confidence=confidence,
        citations=[f"cit:{agent}:{i}" for i in range(n_citations)],
        evidence=[{"indicator_id": f"ind:{agent}", "role": "support"}],
        limitations=[],
        related_entities=[],
    )


def test_weighted_not_arithmetic_mean():
    """Spec: confidences [0.9, 0.5, 0.3] with citations [10, 2, 1].

    Arithmetic mean = (0.9 + 0.5 + 0.3) / 3 = 0.567
    Weighted mean   = (0.9 × 10 + 0.5 × 2 + 0.3 × 1) / 13 = 10.3 / 13 ≈ 0.7923
    """
    synth = ChiefEconomistSynthesizer()
    responses = [
        _response(0.9, 10, "alpha"),
        _response(0.5, 2, "beta"),
        _response(0.3, 1, "gamma"),
    ]
    out = synth.synthesize(
        responses,
        query="why",
        specialist_ids=["alpha", "beta", "gamma"],
    )
    weighted = out["confidence"]
    arithmetic = (0.9 + 0.5 + 0.3) / 3
    # Diverge from arithmetic by a clear margin — proves it's weighted.
    assert weighted == pytest.approx(0.7923, abs=0.005)
    assert weighted > arithmetic + 0.1, (
        f"weighted confidence {weighted} too close to arithmetic mean {arithmetic} — "
        "weighting not applied"
    )


def test_zero_citation_specialists_still_count_with_min_weight():
    """A specialist with 0 citations isn't excluded — it gets weight=1."""
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [
            _response(0.9, 0, "a"),
            _response(0.5, 0, "b"),
        ],
        query="why",
        specialist_ids=["a", "b"],
    )
    # Both weight=1, so unweighted average of 0.9 and 0.5 = 0.7.
    assert out["confidence"] == pytest.approx(0.7, abs=0.01)


def test_single_specialist_confidence_passthrough():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize(
        [_response(0.83, 5, "solo")],
        query="why",
        specialist_ids=["solo"],
    )
    assert out["confidence"] == pytest.approx(0.83, abs=0.001)


def test_no_specialists_returns_zero_confidence():
    synth = ChiefEconomistSynthesizer()
    out = synth.synthesize([], query="why")
    assert out["confidence"] == 0.0
