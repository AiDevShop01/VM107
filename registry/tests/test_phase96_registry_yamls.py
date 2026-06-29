"""Phase 96 registry YAML schema test — flipped from RED (Plan 00 stub) to GREEN in Plan 04.

REQ-96-11 — Every Phase 96 capability MUST have a registry YAML entry so VM107
agents discover it via `lookup_capability` (Phase 47.6 lock,
feedback_capability_registry).

This suite asserts:

- All 5 Phase 96 capability YAMLs exist + parse + carry the canonical schema
- CONTEXT locks on the agent_profile (impact_on_decision=MEDIUM, denied_tools
  least-privilege, allowed_tools set per CONTEXT)
- Contract's node_labels + rel_types match Plan 96-02's Neo4j schema additions
  (cross-references the on-disk RelationshipTypeEnum + OPERATIONAL_LABELS)
- Phase 47.6 LD-7 governance lock: REGISTER_CAPABILITY directives in Plan 04
  (HTML-comment + frontmatter) match each other AND the 4 invocable YAMLs on
  disk (id, type, path, filename stem == declared id — parser Check 4)
- Contract YAML ships WITHOUT a REGISTER_CAPABILITY directive (passive data,
  mirrors Plan 11's tool_template precedent — `contract` is intentionally not
  in the parser's VALID_TYPES frozenset)
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REGISTRY_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Locate Plan 04 in the Dagster sibling repo. Tests are skipped (not failed)
# when the Dagster repo is not co-located with VM107 in the dev tree.
_DAGSTER_CANDIDATES = [
    REGISTRY_ROOT.parent.parent
    / "Dagster"
    / ".planning"
    / "phases"
    / "96-global-macro-map-country-pages-economic-dna-country-knowledge-graph"
    / "96-04-capability-registry-yamls-PLAN.md",
]
PLAN_04_PATH = next((p for p in _DAGSTER_CANDIDATES if p.exists()), None)


# All 5 YAMLs — including the contract (which has no REGISTER_CAPABILITY directive but still ships)
PHASE_96_YAMLS = {
    "agent_profile/vm107.country_dna_generator.yaml": "vm107.country_dna_generator",
    "data_domain/country_knowledge_graph.yaml": "country_knowledge_graph",
    "tool/vm107.tool.find_countries_by_profile_query.yaml": "vm107.tool.find_countries_by_profile_query",
    "contract/country_knowledge_graph_schema.yaml": "contract.country_knowledge_graph_schema",
    "event_type/country_dna_tag_recomputed.yaml": "country_dna_tag_recomputed",
}

# Only invocable types (per parser VALID_TYPES) get REGISTER_CAPABILITY directives.
# `contract` is intentionally excluded — passive data referenced by data_domain.schema_contract.
INVOCABLE_YAMLS = {
    "agent_profile/vm107.country_dna_generator.yaml": ("agent_profile", "vm107.country_dna_generator"),
    "data_domain/country_knowledge_graph.yaml": ("data_domain", "country_knowledge_graph"),
    "tool/vm107.tool.find_countries_by_profile_query.yaml": (
        "tool",
        "vm107.tool.find_countries_by_profile_query",
    ),
    "event_type/country_dna_tag_recomputed.yaml": ("event_type", "country_dna_tag_recomputed"),
}

REQUIRED_TOP_LEVEL = [
    "id",
    "type",
    "status",
    "shipped",
    "last_changed",
    "name",
    "description",
    "capability_type",
    "vm",
    "phase",
    "version",
    "owner",
    "tags",
]


@pytest.mark.parametrize("rel_path,expected_id", list(PHASE_96_YAMLS.items()))
def test_yaml_exists_and_parses(rel_path, expected_id):
    """REQ-96-11: each Phase 96 capability YAML exists, parses, and carries required schema."""
    p = REGISTRY_ROOT / rel_path
    assert p.exists(), f"Missing: {p}"
    data = yaml.safe_load(p.read_text())
    assert data["id"] == expected_id, f"id mismatch in {p}: expected {expected_id}, got {data['id']}"
    for k in REQUIRED_TOP_LEVEL:
        assert k in data, f"Missing required key '{k}' in {p}"
    assert data["phase"] == 96, f"phase != 96 in {p}: got {data['phase']}"
    assert data["shipped"] == 96, f"shipped != 96 in {p}: got {data['shipped']}"
    # tags must be a list and include 'phase-96'
    assert isinstance(data["tags"], list) and "phase-96" in data["tags"], (
        f"tags must include 'phase-96' in {p}: got {data['tags']!r}"
    )


def test_tool_filename_matches_id():
    """Parser Check 4 lock — path filename stem must equal declared id.

    The tool YAML ships at vm107.tool.find_countries_by_profile_query.yaml (NOT
    find_countries_by_profile_query.yaml) so the LD-7 governance parser
    resolves the REGISTER_CAPABILITY directive deterministically.
    """
    p = REGISTRY_ROOT / "tool/vm107.tool.find_countries_by_profile_query.yaml"
    data = yaml.safe_load(p.read_text())
    assert p.stem == data["id"], f"Filename stem {p.stem!r} must equal id {data['id']!r}"


def test_agent_profile_impact_lock():
    """CONTEXT LOCK — impact_on_decision MUST stay MEDIUM (do not change without amendment)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "agent_profile/vm107.country_dna_generator.yaml").read_text()
    )
    assert data["impact_on_decision"] == "MEDIUM", "CONTEXT lock — DO NOT change without amendment"


def test_agent_profile_least_privilege():
    """CONTEXT LOCK — denied_tools must enumerate the least-privilege defaults (Phase 92)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "agent_profile/vm107.country_dna_generator.yaml").read_text()
    )
    denied = data["denied_tools"]
    for tool in ("belief_store.propose", "trade_execution_tool", "code_execution_tool", "filesystem_write"):
        assert tool in denied, f"denied_tools missing least-privilege default: {tool}"


def test_agent_profile_allowed_tools():
    """CONTEXT LOCK — allowed_tools is the 3-tool whitelist for the DNA generator."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "agent_profile/vm107.country_dna_generator.yaml").read_text()
    )
    allowed = data["allowed_tools"]
    for tool in ("find_countries_by_profile_query", "graph_search_tool", "lookup_capability"):
        assert tool in allowed, f"allowed_tools missing required entry: {tool}"


def test_contract_node_labels_complete():
    """Contract's node_labels set ≡ Phase 96 7-label set (cross-validates with Plan 02)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "contract/country_knowledge_graph_schema.yaml").read_text()
    )
    expected = {
        "Country",
        "Currency",
        "Commodity",
        "Industry",
        "Government",
        "CentralBank",
        "EconomicDnaTag",
    }
    assert set(data["node_labels"]) == expected, (
        f"node_labels mismatch: expected {expected}, got {set(data['node_labels'])}"
    )


def test_contract_rel_types_complete():
    """Contract's rel_types set ≡ Phase 96 11-rel set (cross-validates with Plan 02)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "contract/country_knowledge_graph_schema.yaml").read_text()
    )
    expected = {
        "HAS_GOVERNMENT",
        "HAS_CENTRAL_BANK",
        "ISSUES_CURRENCY",
        "PRODUCES",
        "EXPORTS_TO",
        "IMPORTS_FROM",
        "DEPENDS_ON_COMMODITY",
        "HAS_INDUSTRY",
        "HAS_INDICATOR",
        "STRUCTURAL_TAG",
        "DISCUSSED_IN",
    }
    assert set(data["rel_types"]) == expected, (
        f"rel_types mismatch: expected {expected}, got {set(data['rel_types'])}"
    )


def test_data_domain_schema_contract_reference():
    """data_domain.schema_contract must point at the contract YAML's name (transitive discovery)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "data_domain/country_knowledge_graph.yaml").read_text()
    )
    contract = yaml.safe_load(
        (REGISTRY_ROOT / "contract/country_knowledge_graph_schema.yaml").read_text()
    )
    assert data["schema_contract"] == contract["name"], (
        f"schema_contract '{data['schema_contract']}' must equal contract.name '{contract['name']}'"
    )


def test_tool_contract_fields_present():
    """Tool YAML declares request/response contract pointers (Pydantic class names)."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "tool/vm107.tool.find_countries_by_profile_query.yaml").read_text()
    )
    assert "request_contract" in data and isinstance(data["request_contract"], str)
    assert "response_contract" in data and isinstance(data["response_contract"], str)
    assert data["request_contract"] == "FindCountriesByProfileRequest"
    assert data["response_contract"] == "FindCountriesByProfileResponse"


def test_event_type_payload_schema_has_required_fields():
    """Event_type payload schema declares the 4 required fields."""
    data = yaml.safe_load(
        (REGISTRY_ROOT / "event_type/country_dna_tag_recomputed.yaml").read_text()
    )
    for field in ("iso_alpha2", "tag_count", "recomputed_at", "trigger_source"):
        assert field in data["payload_schema"], f"Missing payload field: {field}"


def _parse_directives(text: str) -> list[tuple[str, str, str]]:
    """Parse REGISTER_CAPABILITY HTML-comment directives (matches gsd-plan-checker REGISTER_RE)."""
    directive_re = re.compile(
        r"REGISTER_CAPABILITY:\s*\n\s+type:\s*(\S+)\s*\n\s+id:\s*(\S+)\s*\n\s+path:\s*(\S+)",
        re.MULTILINE,
    )
    return directive_re.findall(text)


@pytest.mark.skipif(
    PLAN_04_PATH is None,
    reason="Dagster sibling repo not present — REGISTER_CAPABILITY parser test skipped",
)
def test_register_capability_directives_match_invocable_yamls():
    """Phase 47.6 LD-7 governance lock — REGISTER_CAPABILITY directives must align with on-disk
    INVOCABLE YAMLs across all three sources of truth: HTML-comment directives, frontmatter
    register_capability block, and the YAML files themselves.

    Contract YAML is excluded — `contract` is not in the parser VALID_TYPES; contracts are
    passive data referenced by data_domain.schema_contract (mirrors Plan 11 tool_template).
    """
    text = PLAN_04_PATH.read_text()
    directives = _parse_directives(text)
    assert len(directives) == 4, (
        f"Expected 4 REGISTER_CAPABILITY directives (contract excluded), found {len(directives)}"
    )

    # Parse frontmatter register_capability block
    fm_match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert fm_match, "Plan 04 missing frontmatter"
    fm = yaml.safe_load(fm_match.group(1))
    rc = fm.get("register_capability", [])
    assert len(rc) == 4, (
        f"Expected 4 entries in register_capability frontmatter (contract excluded), found {len(rc)}"
    )

    # Cross-reference: directive triples ≡ frontmatter triples
    from_directives = {(t, i, p) for (t, i, p) in directives}
    from_frontmatter = {(e["type"], e["id"], e["path"]) for e in rc}
    assert from_directives == from_frontmatter, (
        "REGISTER_CAPABILITY directive/frontmatter mismatch.\n"
        f"Directives: {from_directives}\nFrontmatter: {from_frontmatter}"
    )

    # Cross-reference: each directive's (id, path) matches an on-disk YAML.
    # Plan paths are 'VM107/registry/<type>/<id>.yaml' — strip the leading 'VM107/' to
    # resolve against the VM107 working tree where this test runs.
    for cap_type, cap_id, cap_path in directives:
        relative_to_vm107 = cap_path.removeprefix("VM107/")
        p = REGISTRY_ROOT.parent / relative_to_vm107
        assert p.exists(), f"REGISTER_CAPABILITY path missing on disk: {cap_path} -> {p}"
        data = yaml.safe_load(p.read_text())
        assert data["id"] == cap_id, (
            f"YAML id mismatch at {cap_path}: directive says {cap_id}, file says {data['id']}"
        )
        assert data["type"] == cap_type, (
            f"YAML type mismatch at {cap_path}: directive says {cap_type}, file says {data['type']}"
        )
        # Parser Check 4: filename stem == declared id
        assert p.stem == cap_id, (
            f"Parser Check 4 violation at {cap_path}: filename stem {p.stem!r} != id {cap_id!r}"
        )


@pytest.mark.skipif(
    PLAN_04_PATH is None,
    reason="Dagster sibling repo not present — REGISTER_CAPABILITY parser test skipped",
)
def test_contract_has_no_register_capability_directive():
    """Contract YAML ships via files_modified only — no REGISTER_CAPABILITY directive.

    Mirrors Plan 11's tool_template precedent: `contract` is intentionally not in
    the gsd-plan-checker parser's VALID_TYPES frozenset (16 entries). Contracts are
    discovered transitively via data_domain.schema_contract, not via lookup_capability.
    """
    text = PLAN_04_PATH.read_text()
    for cap_type, cap_id, _cap_path in _parse_directives(text):
        assert cap_type != "contract", (
            f"Contract should not have REGISTER_CAPABILITY directive (found {cap_id})"
        )
        assert "contract.country_knowledge_graph_schema" not in cap_id, (
            f"contract id leaked into REGISTER_CAPABILITY directives: {cap_id}"
        )
