"""Phase 95-12 — ExternalSectorDomainAnalyst specialist contract tests."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.domain import (
    Domain,
    DomainEdge,
    Driver,
    IndicatorRef,
)
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _make_domain(
    *,
    slug: str = "external_sector",
    title: str = "External Sector",
    confidence: float = 0.8,
    drivers: tuple[Driver, ...] | None = None,
    breadth_score: float = 60.0,
    status: SectionStatus = SectionStatus.READY,
) -> Domain:
    if drivers is None:
        drivers = (
            Driver(name="primary_driver", contribution=0.4, direction="up"),
            Driver(name="secondary_driver", contribution=0.2, direction="up"),
            Driver(name="tertiary_driver", contribution=-0.1, direction="down"),
        )
    return Domain(
        section_id=f"domain:{slug}",
        version=1,
        generated_at=datetime.now(tz=timezone.utc),
        snapshot_id="snapshot-test-001",
        freshness_seconds=120,
        confidence=confidence,
        status=status,
        agent="vm102.domain_engine",
        execution_time_ms=42,
        citations=[],
        limitations=[],
        depends_on=["pillars", "indicator_releases"],
        provenance=ProvenanceObject(
            source_event_ids=["evt-1"],
            weights_version=f"US_{slug}_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={"vm101.economic_event": 12},
        ),
        domain_id=slug,
        slug=slug,
        title=title,
        summary=f"{title} domain summary.",
        importance=1,
        primary_pillars=["Growth"],
        primary_analyst=f"vm107.{slug}_domain_analyst",
        health_score=72.0,
        trend_score=15.0,
        breadth_score=breadth_score,
        headline=f"{title} prints firm.",
        risk_level="medium",
        current_state="Improving",
        drivers=list(drivers),
        constraints=[],
        tailwinds=["fiscal impulse", "tight labour market"],
        headwinds=["energy prices"],
        top_indicators=[
            IndicatorRef(indicator_id="IND_A", title="Indicator A", weight=0.4),
            IndicatorRef(indicator_id="IND_B", title="Indicator B", weight=0.3),
            IndicatorRef(indicator_id="IND_C", title="Indicator C", weight=0.2),
            IndicatorRef(indicator_id="IND_D", title="Indicator D", weight=0.05),
            IndicatorRef(indicator_id="IND_E", title="Indicator E", weight=0.05),
        ],
        related_domains=[
            DomainEdge(target_slug="inflation", strength=0.5, relationship="reinforces"),
        ],
        related_themes=[],
        latest_releases=[],
    )


def test_returns_specialist_response_shape():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain()
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    assert isinstance(resp, SpecialistResponse)
    assert 0 <= resp.confidence <= 1
    assert isinstance(resp.citations, list)
    assert isinstance(resp.evidence, list)
    assert isinstance(resp.limitations, list)
    assert isinstance(resp.related_entities, list)


def test_never_recomputes_score():
    """Static guard — agent source must not import the score engines or any LLM SDK."""
    from agents.external_sector_domain_analyst import agent as mod

    src = Path(inspect.getfile(mod)).read_text()
    banned = (
        "level_engine",
        "momentum_engine",
        "breadth_engine",
        "compute_pillar",
        "compute_domain",
        "compute_level",
        "compute_momentum",
        "compute_breadth",
        "import openai",
        "import anthropic",
        "import litellm",
        "from openai",
        "from anthropic",
        "from litellm",
    )
    for needle in banned:
        assert needle not in src, (
            f"banned import/symbol in external_sector_domain_analyst: {needle}"
        )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {
            "compute_pillar",
            "compute_domain",
        }:
            pytest.fail(
                f"external_sector_domain_analyst calls {node.attr} — violates "
                "EXPLAIN-don't-CALCULATE lock (Phase 94 §F.3 + LD-90-1)"
            )


def test_headline_length_60_to_90_words():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain()
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    word_count = len(resp.answer.split())
    assert 60 <= word_count <= 130, (
        f"headline word count {word_count} not in [60, 130]; "
        f"answer: {resp.answer!r}"
    )


def test_citations_from_domain_top_indicators():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain()
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    top_ids = {ind.indicator_id for ind in domain.top_indicators[:5]}
    assert set(resp.citations).issubset(top_ids), (
        f"citations {resp.citations} must be subset of top_indicators[:5] {top_ids}"
    )
    assert len(resp.citations) <= 5


def test_evidence_includes_drivers():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain()
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    assert len(resp.evidence) == len(domain.drivers)
    driver_names = {d.name for d in domain.drivers}
    evidence_names = {e["driver"] for e in resp.evidence}
    assert driver_names == evidence_names


def test_handles_empty_drivers():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain(drivers=())
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    assert resp.evidence == []
    assert any(
        "no drivers" in lim.lower() for lim in resp.limitations
    ), f"limitations must mention no drivers; got {resp.limitations}"


def test_confidence_carry_through_when_upstream_degraded():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain(confidence=0.3)
    resp = ExternalSectorDomainAnalyst().invoke(domain)
    assert resp.confidence < 0.5
    assert any(
        "confidence" in lim.lower() for lim in resp.limitations
    ), f"limitations must mention upstream confidence degradation; got {resp.limitations}"


def test_slug_mismatch_raises():
    from agents.external_sector_domain_analyst import ExternalSectorDomainAnalyst

    domain = _make_domain(slug="wrong_slug", title="Wrong")
    with pytest.raises(AssertionError):
        ExternalSectorDomainAnalyst().invoke(domain)
