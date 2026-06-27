"""Phase 94-05 — Risk Appetite Analyst specialist contract tests."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from contracts.economic_intelligence.pillars import Pillar, PillarState
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _make_pillar(
    *,
    level=40.0,
    state=PillarState.NEGATIVE,
    confidence=0.65,
    contributors=("VIXCLS", "BAMLH0A0HYM2", "T10Y2Y", "DGS10"),
):
    return Pillar(
        name="RiskAppetite",
        level=level,
        momentum={"1m": -0.4, "3m": -0.6, "12m": -0.3},
        breadth=0.4,
        confidence=confidence,
        contributors=list(contributors),
        state=state,
        sparkline_90d=[50.0 - i * 0.1 for i in range(90)],
        provenance=ProvenanceObject(
            source_event_ids=[],
            weights_version="US_RiskAppetite_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={},
        ),
    )


def test_consumes_pillar_emits_specialist_response():
    from agents.risk_analyst import RiskAnalyst

    pillar = _make_pillar()
    resp = RiskAnalyst().invoke(pillar)
    assert isinstance(resp, SpecialistResponse)
    assert len(resp.answer.split()) >= 20


def test_pillar_name_mismatch_raises():
    from agents.risk_analyst import RiskAnalyst

    bad = Pillar(
        name="Growth",
        level=50.0,
        momentum={"1m": 0.0, "3m": 0.0, "12m": 0.0},
        breadth=0.5,
        confidence=0.5,
        contributors=["FOO"],
        state=PillarState.NEUTRAL,
        sparkline_90d=[50.0] * 90,
        provenance=ProvenanceObject(
            source_event_ids=[],
            weights_version="x",
            model_version="na",
            prompt_version="na",
            upstream_sections=[],
            data_versions={},
        ),
    )
    with pytest.raises(AssertionError):
        RiskAnalyst().invoke(bad)


def test_never_recomputes_score():
    from agents.risk_analyst import agent as mod

    src = Path(inspect.getfile(mod)).read_text()
    for needle in ("compute_pillar", "compute_level", "import openai", "import anthropic"):
        assert needle not in src


def test_confidence_carry_through_when_upstream_degraded():
    from agents.risk_analyst import RiskAnalyst

    pillar = _make_pillar(confidence=0.2)
    resp = RiskAnalyst().invoke(pillar)
    assert resp.confidence < 0.5
    assert any("confidence" in lim.lower() for lim in resp.limitations)
