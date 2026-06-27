"""Phase 94-05 — Inflation Analyst specialist contract tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from contracts.economic_intelligence.pillars import Pillar, PillarState
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _make_pillar(
    *,
    level=62.0,
    state=PillarState.POSITIVE,
    confidence=0.75,
    contributors=("CPILFESL", "CPIAUCSL", "PCEPILFE", "CUSR0000SAS"),
):
    return Pillar(
        name="Inflation",
        level=level,
        momentum={"1m": 0.3, "3m": 0.5, "12m": 0.4},
        breadth=0.55,
        confidence=confidence,
        contributors=list(contributors),
        state=state,
        sparkline_90d=[55.0 + i * 0.1 for i in range(90)],
        provenance=ProvenanceObject(
            source_event_ids=["evt-3"],
            weights_version="US_Inflation_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={"vm101.economic_event": 11},
        ),
    )


def test_consumes_pillar_emits_specialist_response():
    from agents.inflation_analyst import InflationAnalyst

    pillar = _make_pillar()
    resp = InflationAnalyst().invoke(pillar)
    assert isinstance(resp, SpecialistResponse)
    assert 0 <= resp.confidence <= 1
    assert len(resp.answer.split()) >= 20
    assert any(c in resp.citations for c in pillar.contributors[:3])
    assert len(resp.evidence) == len(pillar.contributors)


def test_pillar_name_mismatch_raises():
    from agents.inflation_analyst import InflationAnalyst

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
        InflationAnalyst().invoke(bad)


def test_never_recomputes_score():
    from agents.inflation_analyst import agent as mod

    src = Path(inspect.getfile(mod)).read_text()
    for needle in ("compute_pillar", "compute_level", "import openai", "import anthropic"):
        assert needle not in src


def test_confidence_carry_through_when_upstream_degraded():
    from agents.inflation_analyst import InflationAnalyst

    pillar = _make_pillar(confidence=0.4)
    resp = InflationAnalyst().invoke(pillar)
    assert resp.confidence < 0.5
    assert any("confidence" in lim.lower() for lim in resp.limitations)
