"""Phase 95-12 — domain analyst contract tests (parameterized).

Parameterized over the canonical 12 macro domains (CONTEXT §A). Each
domain has a paired Specialist Analyst (VM107 agent); the contract test
ensures each Analyst:

1. Returns a SpecialistResponse (Phase 94 §M contract) with the correct
   envelope shape — non-empty answer, confidence in [0, 1], list-typed
   citations / evidence / limitations / related_entities.
2. Never recomputes the domain score — static-grep guard ensuring no
   engine module imports and no LLM SDK imports (Phase 94 §F.3 lock +
   LD-90-1 LLM-FREE engine lock).
3. AGENT_ID constant matches the registry YAML's `id` field — guards
   against drift between the agent class and the Capability Registry
   entry (Pitfall 5 — no hand-list drift).
4. `consumed_capabilities` in each YAML is a subset of the allowed set
   {domain_engine, domain_baskets, pillars_section}.

Implemented in Plan 95-12 (Wave 6). The Wave 0 xfail stubs are replaced
with concrete tests below.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.domain import (
    Domain,
    DomainEdge,
    Driver,
    IndicatorRef,
)
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.specialist_response import SpecialistResponse


# Per CONTEXT §A canonical 12 — used by every parameterized test in Phase 95.
DOMAIN_SLUGS = [
    "growth",
    "inflation",
    "labour",
    "housing",
    "credit",
    "monetary_policy",
    "fiscal",
    "external_sector",
    "manufacturing",
    "consumer",
    "financial_conditions",
    "commodities",
]

# Allowed consumed_capabilities for any domain analyst (Phase 47.6 capability
# registry — registry-driven dispatch, no router code change).
_ALLOWED_CONSUMED_CAPABILITIES = {
    "domain_engine",
    "domain_baskets",
    "pillars_section",
    # Tools the analyst may invoke (allow-list mirrors profile.yaml allowed_tools)
    "get_domain_health",
    "search_macro_research",
    "lookup_capability",
}


_VM107_ROOT = Path(__file__).resolve().parent.parent.parent


def _class_name(slug: str) -> str:
    return "".join(part.title() for part in slug.split("_")) + "DomainAnalyst"


def _agent_module(slug: str):
    return importlib.import_module(f"agents.{slug}_domain_analyst.agent")


def _agent_class(slug: str):
    return getattr(_agent_module(slug), _class_name(slug))


def _fake_domain(slug: str) -> Domain:
    title = " ".join(part.title() for part in slug.split("_"))
    return Domain(
        section_id=f"domain:{slug}",
        version=1,
        generated_at=datetime.now(tz=timezone.utc),
        snapshot_id="snapshot-contract-test",
        freshness_seconds=120,
        confidence=0.8,
        status=SectionStatus.READY,
        agent="vm102.domain_engine",
        execution_time_ms=42,
        citations=[],
        limitations=[],
        depends_on=["pillars"],
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
        breadth_score=60.0,
        headline=f"{title} prints firm.",
        risk_level="medium",
        current_state="Improving",
        drivers=[
            Driver(name="primary", contribution=0.4, direction="up"),
            Driver(name="secondary", contribution=0.2, direction="up"),
        ],
        constraints=[],
        tailwinds=["fiscal impulse"],
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


# ---------------------------------------------------------------------------
# Test 1: SpecialistResponse shape — parameterized over 12 domains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_returns_specialist_response_shape(slug):
    """Each of the 12 domain analysts returns a SpecialistResponse with
    the full Phase 94 §M envelope (answer, confidence, citations,
    evidence, limitations, related_entities).
    """
    Analyst = _agent_class(slug)
    domain = _fake_domain(slug)
    resp = Analyst().invoke(domain)
    assert isinstance(resp, SpecialistResponse)
    assert isinstance(resp.answer, str) and len(resp.answer) > 0
    assert 0.0 <= resp.confidence <= 1.0
    assert isinstance(resp.citations, list)
    assert isinstance(resp.evidence, list)
    assert isinstance(resp.limitations, list)
    assert isinstance(resp.related_entities, list)


# ---------------------------------------------------------------------------
# Test 2: LLM-FREE engine lock — parameterized over 12 domains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_never_recomputes_score(slug):
    """Static-grep guard: each analyst MUST consume the domain
    health_score computed by VM102.DomainEngine; it MUST NOT re-derive a
    score from raw basket indicators (LLM-FREE compute lock — Phase 94
    §F.3 + LD-90-1).
    """
    agent_path = _VM107_ROOT / "agents" / f"{slug}_domain_analyst" / "agent.py"
    source = agent_path.read_text()
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
        assert needle not in source, (
            f"banned symbol {needle!r} found in {agent_path.relative_to(_VM107_ROOT)}"
        )


# ---------------------------------------------------------------------------
# Test 3: AGENT_ID matches profile YAML id — registry/agent drift guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_agent_id_matches_profile(slug):
    """Each agent's AGENT_ID constant matches the Capability Registry
    YAML's `id` field (Pitfall 5 — no hand-list drift between code and
    registry).
    """
    Analyst = _agent_class(slug)
    yaml_path = (
        _VM107_ROOT
        / "registry"
        / "agent_profile"
        / f"vm107.{slug}_domain_analyst.yaml"
    )
    profile = yaml.safe_load(yaml_path.read_text())
    assert Analyst.AGENT_ID == profile["id"], (
        f"{slug}: AGENT_ID={Analyst.AGENT_ID!r} does not match "
        f"registry id={profile['id']!r}"
    )
    assert profile["phase"] == 95
    assert profile["shipped"] == 95
    assert profile["capability_type"] == "agent"
    assert profile["vm"] == "vm107"


# ---------------------------------------------------------------------------
# Test 4: consumed_capabilities subset check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_consumed_capabilities_subset(slug):
    """Each YAML's consumed_capabilities is a subset of the allowed set
    {domain_engine, domain_baskets, pillars_section, get_domain_health,
    search_macro_research, lookup_capability} — guards against accidental
    capability creep.
    """
    yaml_path = (
        _VM107_ROOT
        / "registry"
        / "agent_profile"
        / f"vm107.{slug}_domain_analyst.yaml"
    )
    profile = yaml.safe_load(yaml_path.read_text())
    consumed = set(profile.get("consumed_capabilities", []))
    unknown = consumed - _ALLOWED_CONSUMED_CAPABILITIES
    assert not unknown, (
        f"{slug}: consumed_capabilities contains unknown entries: {sorted(unknown)}"
    )
    assert consumed, f"{slug}: consumed_capabilities must be non-empty"
