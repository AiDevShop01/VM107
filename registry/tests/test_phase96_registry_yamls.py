"""Phase 96 Wave 0 RED stub — REQ-96-11 Capability Registry YAMLs.

Plan 96-04 (Capability Registry YAMLs) flips these to GREEN.

Per Phase 47.6 register-on-ship lock, every Phase 96 capability MUST have a
registry YAML entry. Plan 96-04 ships:

  - agent_profile/vm107.country_dna_generator.yaml
  - data_domain/country_knowledge_graph.yaml
  - tool/find_countries_by_profile_query.yaml
  - contract/country_knowledge_graph_schema.yaml
  - event_type/country_dna_tag_recomputed.yaml

All 5 must parse against the existing registry schema validators in
VM107/registry/_schemas/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REGISTRY_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PHASE96_YAMLS = [
    "agent_profile/vm107.country_dna_generator.yaml",
    "data_domain/country_knowledge_graph.yaml",
    "tool/find_countries_by_profile_query.yaml",
    "contract/country_knowledge_graph_schema.yaml",
    "event_type/country_dna_tag_recomputed.yaml",
]


@pytest.mark.parametrize("relpath", EXPECTED_PHASE96_YAMLS)
@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-04 flips to GREEN")
def test_phase96_registry_yaml_exists(relpath):
    """REQ-96-11: each Phase 96 capability YAML is present on disk."""
    assert (REGISTRY_ROOT / relpath).exists(), f"missing: {relpath}"


@pytest.mark.parametrize("relpath", EXPECTED_PHASE96_YAMLS)
@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-04 flips to GREEN")
def test_phase96_registry_yaml_parses(relpath):
    """REQ-96-11: each YAML parses + validates against its registry schema."""
    raise NotImplementedError(f"Plan 96-04: implement schema validation for {relpath}")


@pytest.mark.xfail(strict=False, reason="Wave 0 stub — Plan 96-04 flips to GREEN")
def test_lookup_capability_discovers_country_dna_generator():
    """REQ-96-11: lookup_capability('vm107.country_dna_generator') returns the YAML payload."""
    raise NotImplementedError("Plan 96-04: implement against Phase 47.6 lookup_capability")
