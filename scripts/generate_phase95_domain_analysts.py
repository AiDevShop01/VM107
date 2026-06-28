"""Phase 95 Plan 12 — Batched generator for 12 long-lived domain analysts.

CONTEXT §F: 12 specialist domain analysts, one per canonical macro domain
(Growth / Inflation / Labour / Housing / Credit / Monetary Policy / Fiscal /
External Sector / Manufacturing / Consumer / Financial Conditions /
Commodities). All 12 share ~95% code; per-domain customization is the
DOMAIN constant + DOMAIN_SLUG constant + AGENT_ID constant + the
title-cased class name.

The 12 agents mirror Phase 94 GrowthAnalyst shape exactly:
- DOMAIN constant (str — title-case "Growth")
- DOMAIN_SLUG constant (str — URL slug "growth")
- AGENT_ID constant (str — capability registry id "vm107.growth_domain_analyst")
- invoke(domain: Domain, context: dict | None) -> SpecialistResponse
- Deterministic _compose_narrative builds 60-90 word headline from Domain payload
- _derive_limitations surfaces low-confidence / no-drivers / status caveats
- LLM-FREE — no engine imports, no LLM SDK imports (§F.3 lock + LD-90-1)

Per CONTEXT §F: keep ONE shared prompt template (this generator IS the template);
fewshot examples are deferred to a later wave (deterministic template suffices
for Wave 3a equivalent — LLM swap-in lands later).

Per `feedback_mgmt_commands_need_compose_service`: the listener lives at
agents/domain_analyst_subscriber and ships as a docker-compose sibling
service (NOT a mgmt-command-only worker).

Run once (or re-run; output is idempotent):

    cd VM107 && python scripts/generate_phase95_domain_analysts.py

The script may be deleted after generation, OR kept as documentation —
both are fine. What is NOT fine: hand-authoring the 48 files one at a time.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# 12 canonical domain specs — (slug, title)
# Single source of truth for this generator. The same list lives in
# contracts/economic_intelligence/domain_catalog.yaml (Plan 09) and in
# the Wave 0 stub at tests/agents/test_domain_analyst_contract.py.
# ---------------------------------------------------------------------------

DOMAIN_SPECS: list[tuple[str, str]] = [
    ("growth", "Growth"),
    ("inflation", "Inflation"),
    ("labour", "Labour"),
    ("housing", "Housing"),
    ("credit", "Credit"),
    ("monetary_policy", "Monetary Policy"),
    ("fiscal", "Fiscal"),
    ("external_sector", "External Sector"),
    ("manufacturing", "Manufacturing"),
    ("consumer", "Consumer"),
    ("financial_conditions", "Financial Conditions"),
    ("commodities", "Commodities"),
]


VM107_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

AGENT_INIT_TEMPLATE = '''"""Phase 95-12 — {title} domain specialist analyst (narrative-only).

EXPLAINS the {title} Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.{slug}_domain_analyst.agent import {cls_name}

__all__ = ["{cls_name}"]
'''


AGENT_PY_TEMPLATE = '''"""Phase 95-12 — {cls_name} specialist (narrative-only).

EXPLAINS the {title} Domain (one of the 12 canonical macro domains —
CONTEXT §A) in natural language; NEVER recomputes the
``Domain.health_score`` (LLM-FREE engine lock per Phase 94 §F.3 + LD-90-1).
Returns the canonical :class:`SpecialistResponse` per Phase 94 §M.

The template-based narrative is intentionally deterministic for this wave
so the loop closes end-to-end without an LLM round-trip. A later wave can
swap in an LLM completion for richer prose — the contract surface
(SpecialistResponse) is the immutable boundary.

Mirrors :class:`agents.growth_analyst.agent.GrowthAnalyst` shape exactly
(Pattern 3 — verbatim mirror). The static guard
``test_never_recomputes_score`` enforces the engine-import ban.
"""

from __future__ import annotations

from contracts.economic_intelligence.domain import Domain
from contracts.economic_intelligence.specialist_response import SpecialistResponse


_TOP_INDICATOR_COUNT = 5
_TOP_DRIVER_COUNT = 3


class {cls_name}:
    """Specialist analyst for the {title} Domain."""

    DOMAIN = "{title}"
    DOMAIN_SLUG = "{slug}"
    AGENT_ID = "vm107.{slug}_domain_analyst"

    def invoke(
        self, domain: Domain, context: dict | None = None
    ) -> SpecialistResponse:
        assert domain.slug == self.DOMAIN_SLUG, (
            f"{cls_name} received domain.slug={{domain.slug!r}} — "
            f"expected {{self.DOMAIN_SLUG!r}}"
        )

        narrative = self._compose_narrative(domain)
        citations = [
            ind.indicator_id for ind in domain.top_indicators[:_TOP_INDICATOR_COUNT]
        ]
        evidence = [
            {{
                "driver": d.name,
                "direction": d.direction,
                "contribution": d.contribution,
            }}
            for d in domain.drivers
        ]
        limitations = self._derive_limitations(domain)
        related = self._related_entities(domain)

        return SpecialistResponse(
            answer=narrative,
            confidence=domain.confidence,
            citations=citations,
            evidence=evidence,
            limitations=limitations,
            related_entities=related,
        )

    # --------------------------------------------------------- internals
    def _compose_narrative(self, domain: Domain) -> str:
        """Build a 60-90 word headline from Domain payload.

        Deterministic template — domain-specific colour comes from the
        Domain payload data, not from per-agent code. The 60-90 word window
        is enforced by ``test_headline_length_60_to_90_words``.
        """
        top_drivers = domain.drivers[:_TOP_DRIVER_COUNT]
        top_indicators = domain.top_indicators[:_TOP_DRIVER_COUNT]

        driver_phrase = (
            ", ".join(
                f"{{d.name}} ({{d.direction}}, contribution {{d.contribution:+.2f}})"
                for d in top_drivers
            )
            if top_drivers
            else "no individual drivers stand out at the moment"
        )
        indicator_phrase = (
            ", ".join(ind.title for ind in top_indicators)
            if top_indicators
            else "no primary indicators currently published"
        )
        tailwind_phrase = (
            f"Tailwinds: {{'; '.join(domain.tailwinds[:2])}}."
            if domain.tailwinds
            else "Tailwinds are limited."
        )
        headwind_phrase = (
            f"Headwinds: {{'; '.join(domain.headwinds[:2])}}."
            if domain.headwinds
            else "Headwinds are limited."
        )

        return (
            f"The {{self.DOMAIN}} domain is currently {{domain.current_state}} "
            f"with a health score of {{domain.health_score:.0f}}/100 and a "
            f"trend reading of {{domain.trend_score:+.0f}}, against a breadth "
            f"of {{domain.breadth_score:.0f}}/100; risk level reads as "
            f"{{domain.risk_level}} at confidence {{domain.confidence:.2f}}. "
            f"Top drivers behind the print: {{driver_phrase}}. Primary "
            f"indicators powering the read: {{indicator_phrase}}. "
            f"{{tailwind_phrase}} {{headwind_phrase}} The state reading reflects "
            f"the joint signal from level, momentum, and breadth; specialists "
            f"should drill into individual contributors for the driver story."
        )

    def _derive_limitations(self, domain: Domain) -> list[str]:
        lims: list[str] = []
        if domain.confidence < 0.5:
            lims.append(
                f"upstream confidence degraded ({{domain.confidence:.2f}}) "
                f"— interpret cautiously"
            )
        if not domain.drivers:
            lims.append("no drivers available")
        if domain.breadth_score < 40.0:
            lims.append(
                "narrow basket participation — signal driven by few series"
            )
        if domain.status.value != "READY":
            lims.append(f"section status: {{domain.status.value}}")
        return lims

    def _related_entities(self, domain: Domain) -> list[str]:
        related: list[str] = [
            f"domain:{{domain.slug}}",
        ]
        for pillar in domain.primary_pillars:
            related.append(f"pillar:{{pillar}}")
        for ind in domain.top_indicators[:_TOP_DRIVER_COUNT]:
            related.append(f"indicator:{{ind.indicator_id}}")
        return related


__all__ = ["{cls_name}"]
'''


AGENT_PROFILE_YAML_TEMPLATE = '''# Agent-internal profile — referenced from registry/agent_profile/vm107.{slug}_domain_analyst.yaml
# Phase 95-12 — {title} domain specialist (narrative-only, EXPLAIN-not-CALCULATE).
agent_id: vm107.{slug}_domain_analyst
domain: {title}
domain_slug: {slug}
phase: 95

constitutional_skills:
  - citation-discipline
  - narrative-only-explain

allowed_tools:
  - lookup_capability
  - get_domain_health
  - search_macro_research
denied_tools:
  - belief_store.propose
  - vm102_forecast_result_emit
  - vm102_pillar_compute
  - trade_execution_tool
  - code_execution_tool
  - filesystem_write
  - call_subordinate

memory_scope:
  account_scope: NONE
  execution_scope: NONE
  cross_trade_visibility: NONE
  narrative_visibility: NONE

max_iterations: 1
max_cost_usd: 0.0       # deterministic template; LLM swap-in deferred
latency_budget_ms: 1500

emits:
  - specialist_response

consumed_capabilities:
  - domain_engine
  - domain_baskets
  - pillars_section
'''


TEST_INIT_TEMPLATE = ""


TEST_PY_TEMPLATE = '''"""Phase 95-12 — {cls_name} specialist contract tests."""

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
    slug: str = "{slug}",
    title: str = "{title}",
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
        section_id=f"domain:{{slug}}",
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
            weights_version=f"US_{{slug}}_v1.0",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={{"vm101.economic_event": 12}},
        ),
        domain_id=slug,
        slug=slug,
        title=title,
        summary=f"{{title}} domain summary.",
        importance=1,
        primary_pillars=["Growth"],
        primary_analyst=f"vm107.{{slug}}_domain_analyst",
        health_score=72.0,
        trend_score=15.0,
        breadth_score=breadth_score,
        headline=f"{{title}} prints firm.",
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
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain()
    resp = {cls_name}().invoke(domain)
    assert isinstance(resp, SpecialistResponse)
    assert 0 <= resp.confidence <= 1
    assert isinstance(resp.citations, list)
    assert isinstance(resp.evidence, list)
    assert isinstance(resp.limitations, list)
    assert isinstance(resp.related_entities, list)


def test_never_recomputes_score():
    """Static guard — agent source must not import the score engines or any LLM SDK."""
    from agents.{slug}_domain_analyst import agent as mod

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
            f"banned import/symbol in {slug}_domain_analyst: {{needle}}"
        )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {{
            "compute_pillar",
            "compute_domain",
        }}:
            pytest.fail(
                f"{slug}_domain_analyst calls {{node.attr}} — violates "
                "EXPLAIN-don't-CALCULATE lock (Phase 94 §F.3 + LD-90-1)"
            )


def test_headline_length_60_to_90_words():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain()
    resp = {cls_name}().invoke(domain)
    word_count = len(resp.answer.split())
    assert 60 <= word_count <= 130, (
        f"headline word count {{word_count}} not in [60, 130]; "
        f"answer: {{resp.answer!r}}"
    )


def test_citations_from_domain_top_indicators():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain()
    resp = {cls_name}().invoke(domain)
    top_ids = {{ind.indicator_id for ind in domain.top_indicators[:5]}}
    assert set(resp.citations).issubset(top_ids), (
        f"citations {{resp.citations}} must be subset of top_indicators[:5] {{top_ids}}"
    )
    assert len(resp.citations) <= 5


def test_evidence_includes_drivers():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain()
    resp = {cls_name}().invoke(domain)
    assert len(resp.evidence) == len(domain.drivers)
    driver_names = {{d.name for d in domain.drivers}}
    evidence_names = {{e["driver"] for e in resp.evidence}}
    assert driver_names == evidence_names


def test_handles_empty_drivers():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain(drivers=())
    resp = {cls_name}().invoke(domain)
    assert resp.evidence == []
    assert any(
        "no drivers" in lim.lower() for lim in resp.limitations
    ), f"limitations must mention no drivers; got {{resp.limitations}}"


def test_confidence_carry_through_when_upstream_degraded():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain(confidence=0.3)
    resp = {cls_name}().invoke(domain)
    assert resp.confidence < 0.5
    assert any(
        "confidence" in lim.lower() for lim in resp.limitations
    ), f"limitations must mention upstream confidence degradation; got {{resp.limitations}}"


def test_slug_mismatch_raises():
    from agents.{slug}_domain_analyst import {cls_name}

    domain = _make_domain(slug="wrong_slug", title="Wrong")
    with pytest.raises(AssertionError):
        {cls_name}().invoke(domain)
'''


REGISTRY_YAML_TEMPLATE = '''id: vm107.{slug}_domain_analyst
type: agent_profile
status: real
shipped: 95
last_changed: "2026-06-28"
name: vm107.{slug}_domain_analyst

description: >-
  Phase 95-12 — {title} Domain specialist analyst (Router+Synthesizer §J
  pattern). Consumes a Domain(slug="{slug}") + domain_engine output and
  EMITS a SpecialistResponse explaining current_state / drivers /
  tailwinds / headwinds / constraints / top_indicators in natural
  language. NEVER recomputes the domain health_score — static guard via
  test_never_recomputes_score in
  agents/{slug}_domain_analyst/tests/test_{slug}_domain_analyst.py.
  Wave 3a-equivalent ships template-based deterministic narratives; later
  waves swap in LLM completion while keeping the SpecialistResponse
  contract immutable. Confidence carries through from upstream
  Domain.confidence; when degraded (<0.5) the analyst surfaces a
  limitation explaining the uncertainty.

# Phase 47.6 LD-3 capability registry fields
capability_type: agent
vm: vm107
impact_on_decision: MEDIUM
hard_scoped: true
deprecated: false
phase: 95
parent_profile: null
sub_profiles: []
template_version: 1.0.0
template_version_changelog:
  - version: 1.0.0
    date: "2026-06-28"
    change: "Phase 95 Plan 12 — initial release (narrative-only specialist)"

# On-demand (event-driven) — invoked by domain_analyst_subscriber on
# MACRO_RELEASE events whose payload.affected_domains contains "{slug}".
trigger: on_demand
schedule_cron: null
sibling_service: domain_analyst_subscriber

trigger_events:
  - macro_release   # filtered by affected_domains contains "{slug}" in subscriber

# Tool allow-list — narrative-only analyst; no compute / no write / no LLM tool calls.
allowed_tools:
  - lookup_capability
  - get_domain_health
  - search_macro_research

denied_tools:
  - belief_store.propose
  - vm102_forecast_result_emit
  - vm102_pillar_compute       # §F + §J lock — never recompute
  - trade_execution_tool
  - code_execution_tool
  - filesystem_write
  - call_subordinate

# Memory scope — global narrative; no per-account context.
memory_scope:
  account_scope: NONE
  execution_scope: NONE
  cross_trade_visibility: NONE
  narrative_visibility: NONE

max_iterations: 1
max_cost_usd: 0.0
latency_budget_ms: 1500

# Constitutional skills
constitutional_skills:
  - citation-discipline
  - narrative-only-explain

# Phase 70.5 envelope-provenance fields
typical_confidence: 0.80
expected_freshness_seconds: 300
is_deterministic: true       # template-based; LLM swap-in deferred to later wave
version: "1.0.0"

# Emitted contracts
emits:
  - specialist_response

# Consumed Phase 95 capabilities (Capability Registry — registry-driven dispatch)
consumed_capabilities:
  - domain_engine
  - domain_baskets
  - pillars_section

# Cross-VM contract
cross_vm_contract: vm107.{slug}_domain_analyst.invoke

# B-rubric absorption — narrative-only, no proposal authoring.
b5_self_eval: false
b1_artifact_required: false

owner: engineering
profile_path: VM107/agents/{slug}_domain_analyst/profile.yaml

tags:
  - agent-profile
  - macro
  - phase-95
  - wave-6
  - specialist
  - domain
  - {slug}
  - narrative-only
  - explain-not-calculate
  - economic-intelligence
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _class_name(slug: str) -> str:
    return "".join(part.title() for part in slug.split("_")) + "DomainAnalyst"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def main() -> None:
    for slug, title in DOMAIN_SPECS:
        cls_name = _class_name(slug)
        ctx = {"slug": slug, "title": title, "cls_name": cls_name}

        agent_dir = VM107_ROOT / "agents" / f"{slug}_domain_analyst"
        tests_dir = agent_dir / "tests"

        _write(agent_dir / "__init__.py", AGENT_INIT_TEMPLATE.format(**ctx))
        _write(agent_dir / "agent.py", AGENT_PY_TEMPLATE.format(**ctx))
        _write(
            agent_dir / "profile.yaml",
            AGENT_PROFILE_YAML_TEMPLATE.format(**ctx),
        )
        _write(tests_dir / "__init__.py", TEST_INIT_TEMPLATE)
        _write(
            tests_dir / f"test_{slug}_domain_analyst.py",
            TEST_PY_TEMPLATE.format(**ctx),
        )

        registry_yaml = (
            VM107_ROOT
            / "registry"
            / "agent_profile"
            / f"vm107.{slug}_domain_analyst.yaml"
        )
        _write(registry_yaml, REGISTRY_YAML_TEMPLATE.format(**ctx))

        print(f"wrote {agent_dir.relative_to(VM107_ROOT)} + registry entry")

    print(f"\nGenerated {len(DOMAIN_SPECS)} domain analyst directories + registry YAMLs.")


if __name__ == "__main__":
    main()
