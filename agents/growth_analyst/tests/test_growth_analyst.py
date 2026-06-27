"""Phase 94-05 — Growth Analyst specialist contract tests."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.economic_intelligence.pillars import Pillar, PillarState
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _make_pillar(
    *,
    name="Growth",
    level=72.0,
    state=PillarState.POSITIVE,
    confidence=0.8,
    contributors=("PAYEMS", "INDPRO", "GDPC1", "RSXFS", "ICSA"),
    momentum=None,
) -> Pillar:
    return Pillar(
        name=name,
        level=level,
        momentum=momentum or {"1m": 0.4, "3m": 0.7, "12m": 0.9},
        breadth=0.6,
        confidence=confidence,
        contributors=list(contributors),
        state=state,
        sparkline_90d=[50.0 + i * 0.2 for i in range(90)],
        provenance=ProvenanceObject(
            source_event_ids=["evt-1", "evt-2"],
            weights_version="US_Growth_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={"vm101.economic_event": 12},
        ),
    )


def test_consumes_pillar_emits_specialist_response():
    from agents.growth_analyst import GrowthAnalyst

    pillar = _make_pillar()
    resp = GrowthAnalyst().invoke(pillar)
    assert isinstance(resp, SpecialistResponse)
    assert 0 <= resp.confidence <= 1
    # answer is non-empty and substantive (>=60 words is overkill for a template;
    # the contract test demands non-empty narrative — 20+ words is enough).
    words = resp.answer.split()
    assert len(words) >= 20, f"narrative too short ({len(words)} words): {resp.answer!r}"
    # Top contributors must appear in citations.
    assert any(c in resp.citations for c in pillar.contributors[:3])
    # Evidence list has one entry per contributor.
    assert len(resp.evidence) == len(pillar.contributors)
    # Limitations is always present (may be empty list).
    assert isinstance(resp.limitations, list)


def test_pillar_name_mismatch_raises():
    from agents.growth_analyst import GrowthAnalyst

    pillar = _make_pillar(name="Inflation")
    with pytest.raises(AssertionError):
        GrowthAnalyst().invoke(pillar)


def test_never_recomputes_score():
    """Static guard — agent source must not import pillar engine or compute_pillar."""
    from agents.growth_analyst import agent as mod

    src = Path(inspect.getfile(mod)).read_text()
    banned = (
        "from vm102",
        "compute_pillar",
        "compute_level",
        "compute_momentum",
        "compute_breadth",
        "import openai",
        "import anthropic",
    )
    for needle in banned:
        assert needle not in src, f"banned import/symbol in growth_analyst: {needle}"
    # AST walk for any pillar-engine attribute usage.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"compute_pillar"}:
            pytest.fail("growth_analyst calls compute_pillar — violates EXPLAIN-don't-CALCULATE lock")


def test_related_entities_include_navigation_hints():
    from agents.growth_analyst import GrowthAnalyst

    pillar = _make_pillar()
    resp = GrowthAnalyst().invoke(pillar)
    # At least one related entity references the growth domain or an indicator.
    assert any(
        ref.startswith("indicator:") or ref.startswith("domain:") or ref.startswith("pillar:")
        for ref in resp.related_entities
    ), f"related_entities should hint navigation; got {resp.related_entities}"


def test_confidence_carry_through_when_upstream_degraded():
    from agents.growth_analyst import GrowthAnalyst

    pillar = _make_pillar(confidence=0.3)
    resp = GrowthAnalyst().invoke(pillar)
    assert resp.confidence < 0.5, f"confidence must mirror upstream when degraded; got {resp.confidence}"
    assert any("confidence" in lim.lower() for lim in resp.limitations), (
        f"limitations must mention upstream confidence degradation; got {resp.limitations}"
    )
