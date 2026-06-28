"""Phase 95 Wave 0 stub — Capability Registry presence tests (Phase 47.6 lock).

Per the Phase 47.6 register-on-ship lock, every Phase 95 capability MUST
have a registry YAML entry. This test parameterizes over the expected
YAML files and asserts each exists in ``VM107/registry/``.

Expected YAMLs (filled in by Plans 95-09 through 95-12):

- 12 agent profiles  — one per canonical domain analyst
- 12 data domains    — one per canonical macro domain
- 2 tools            — get_domain_health, manage_watchlist
- 1 contract         — domain (the Domain Pydantic contract)

All tests xfailed until Plans 95-09..12 ship the YAMLs.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Per CONTEXT §A canonical 12.
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


EXPECTED_AGENT_YAMLS = [
    f"agent_profile/vm107.{slug}_domain_analyst.yaml" for slug in DOMAIN_SLUGS
]
EXPECTED_DATA_DOMAIN_YAMLS = [
    f"data_domain/macro_domain_{slug}.yaml" for slug in DOMAIN_SLUGS
]
EXPECTED_TOOL_YAMLS = [
    "tool/get_domain_health.yaml",
    "tool/manage_watchlist.yaml",
]
EXPECTED_CONTRACT_YAMLS = ["contract/domain.yaml"]


REGISTRY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relpath", EXPECTED_AGENT_YAMLS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — agent YAMLs land in Plan 95-12 (Domain Analysts)",
)
def test_agent_profile_yaml_exists(relpath):
    assert (REGISTRY_ROOT / relpath).is_file(), f"Missing: {relpath}"


@pytest.mark.parametrize("relpath", EXPECTED_DATA_DOMAIN_YAMLS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — data_domain YAMLs land in Plan 95-11 (Domain Engine)",
)
def test_data_domain_yaml_exists(relpath):
    assert (REGISTRY_ROOT / relpath).is_file(), f"Missing: {relpath}"


@pytest.mark.parametrize("relpath", EXPECTED_TOOL_YAMLS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — tool YAMLs land in Plans 95-08 + 95-13",
)
def test_tool_yaml_exists(relpath):
    assert (REGISTRY_ROOT / relpath).is_file(), f"Missing: {relpath}"


@pytest.mark.parametrize("relpath", EXPECTED_CONTRACT_YAMLS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — contract YAML lands in Plan 95-09 (Domain Contract)",
)
def test_contract_yaml_exists(relpath):
    assert (REGISTRY_ROOT / relpath).is_file(), f"Missing: {relpath}"
