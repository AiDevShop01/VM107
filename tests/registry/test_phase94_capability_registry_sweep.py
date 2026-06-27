"""Phase 94 Wave 0 — Capability Registry sweep RED scaffold (REQ-94-9).

Becomes GREEN incrementally:
- 94-02 (events + event_bus service)
- 94-04 (pillar engine data_domain)
- 94-05 (theme engine + specialists)
- 94-06 (5 base agents + synthesizer)
- 94-10 (data_domain + tool finalization)

Enumerates ALL expected registry entries (per CONTEXT.md §N refinement):
- 10 agent_profile YAMLs
- 9 section + 1 aggregate contract YAMLs
- 8 EconomicEvent type YAMLs
- 1 data_domain YAML
- 1 tool YAML
- 4 service YAMLs
"""

from __future__ import annotations

from pathlib import Path

import pytest


EXPECTED_AGENT_PROFILES = [
    "vm107.executive_summary",
    "vm107.theme_monitor",
    "vm107.timeline",
    "vm107.central_bank_summariser",
    "vm107.macro_ask_router",
    "vm107.chief_economist_synthesizer",
    "vm107.growth_analyst",
    "vm107.inflation_analyst",
    "vm107.liquidity_analyst",
    "vm107.risk_analyst",
]

EXPECTED_CONTRACTS = [
    "economic_snapshot",
    "executive_summary_section",
    "pillars_section",
    "theme_monitor_section",
    "timeline_section",
    "central_bank_section",
    "forecast_section",
    "research_section",
    "relationship_section",
    "alerts_section",
]

EXPECTED_EVENT_TYPES = [
    "macro_release",
    "central_bank",
    "regime_change",
    "discovery",
    "forecast_update",
    "research",
    "alert",
    "structural_update",
]

EXPECTED_DATA_DOMAINS = ["macro_situation"]
EXPECTED_TOOLS = ["ask_macro_router"]
EXPECTED_SERVICES = [
    "snapshot_coordinator",
    "pillar_engine",
    "theme_engine",
    "event_bus",
]


REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "registry"


@pytest.mark.parametrize("agent_id", EXPECTED_AGENT_PROFILES)
def test_agent_profile_yaml_exists(agent_id):
    path = REGISTRY_ROOT / "agent_profile" / f"{agent_id}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 6 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )


@pytest.mark.parametrize("contract_id", EXPECTED_CONTRACTS)
def test_contract_yaml_exists(contract_id):
    path = REGISTRY_ROOT / "contract" / f"{contract_id}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 2/10 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )


@pytest.mark.parametrize("event_type", EXPECTED_EVENT_TYPES)
def test_event_type_yaml_exists(event_type):
    path = REGISTRY_ROOT / "event_type" / f"{event_type}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 2 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )


@pytest.mark.parametrize("data_domain", EXPECTED_DATA_DOMAINS)
def test_data_domain_yaml_exists(data_domain):
    path = REGISTRY_ROOT / "data_domain" / f"{data_domain}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 10 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )


@pytest.mark.parametrize("tool_id", EXPECTED_TOOLS)
def test_tool_yaml_exists(tool_id):
    path = REGISTRY_ROOT / "tool" / f"{tool_id}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 10 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )


@pytest.mark.parametrize("service_id", EXPECTED_SERVICES)
def test_service_yaml_exists(service_id):
    path = REGISTRY_ROOT / "service" / f"{service_id}.yaml"
    if not path.exists():
        pytest.fail(
            f"Wave 2/4/5 must create {path.relative_to(REGISTRY_ROOT.parent)} (REQ-94-9 sweep)"
        )
