"""Phase 94 Wave 0 — Specialist typed-contract scaffold.

Flipped GREEN by 94-05: see per-agent test files under
``VM107/agents/<analyst>/tests/`` for the full per-specialist suites.
This file parametrizes a uniform contract check across all 4
specialists so the SpecialistResponse contract stays uniform.
"""

from __future__ import annotations

import pytest

from contracts.economic_intelligence.pillars import Pillar, PillarState
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _pillar(name: str, *, confidence: float = 0.8) -> Pillar:
    contributors_by_name = {
        "Growth": ["PAYEMS", "INDPRO", "GDPC1", "RSXFS", "ICSA"],
        "Inflation": ["CPILFESL", "CPIAUCSL", "PCEPILFE"],
        "Liquidity": ["WALCL", "WRESBAL", "DGS10"],
        "RiskAppetite": ["VIXCLS", "BAMLH0A0HYM2", "T10Y2Y"],
    }
    return Pillar(
        name=name,
        level=60.0,
        momentum={"1m": 0.2, "3m": 0.3, "12m": 0.4},
        breadth=0.5,
        confidence=confidence,
        contributors=contributors_by_name[name],
        state=PillarState.POSITIVE,
        sparkline_90d=[55.0 + i * 0.1 for i in range(90)],
        provenance=ProvenanceObject(
            source_event_ids=[],
            weights_version=f"US_{name}_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=[],
            data_versions={},
        ),
    )


_ANALYSTS = [
    ("Growth", "agents.growth_analyst", "GrowthAnalyst"),
    ("Inflation", "agents.inflation_analyst", "InflationAnalyst"),
    ("Liquidity", "agents.liquidity_analyst", "LiquidityAnalyst"),
    ("RiskAppetite", "agents.risk_analyst", "RiskAnalyst"),
]


@pytest.mark.parametrize("pillar_name,module,cls", _ANALYSTS)
def test_growth_analyst_invoke_returns_specialist_response_shape(pillar_name, module, cls):
    import importlib

    mod = importlib.import_module(module)
    Analyst = getattr(mod, cls)
    pillar = _pillar(pillar_name)
    resp = Analyst().invoke(pillar)
    assert isinstance(resp, SpecialistResponse)
    assert len(resp.answer) > 0
    assert 0.0 <= resp.confidence <= 1.0
    assert isinstance(resp.citations, list)
    assert isinstance(resp.evidence, list) and len(resp.evidence) >= 1
    assert isinstance(resp.limitations, list)
    assert isinstance(resp.related_entities, list)


@pytest.mark.parametrize("pillar_name,module,cls", _ANALYSTS)
def test_confidence_carry_through(pillar_name, module, cls):
    import importlib

    mod = importlib.import_module(module)
    Analyst = getattr(mod, cls)
    degraded = _pillar(pillar_name, confidence=0.3)
    resp = Analyst().invoke(degraded)
    assert resp.confidence < 0.5, (
        f"{cls}: confidence must mirror upstream when degraded (got {resp.confidence})"
    )
    assert any("confidence" in lim.lower() for lim in resp.limitations), (
        f"{cls}: limitations must mention upstream confidence degradation"
    )
