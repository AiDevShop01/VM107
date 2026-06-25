"""Phase 92 — Capability Registry sweep across all 9 Phase-92 YAMLs.

Per MINOR-4 enumerated manifest:
  1. VM107/registry/data_domains/research_documents.yaml          (Plan 1)
  2. VM107/registry/agent_profile/vm107.research_classification_agent.yaml (Plan 3)
  3. VM107/registry/contract/phase92_neo4j_schema_extension.yaml (Plan 4)
  4. VM107/registry/agent_profile/vm107.research_summarisation_agent.yaml (Plan 5)
  5. VM107/registry/agent_profile/vm107.research_citation_agent.yaml      (Plan 5)
  6. VM107/registry/agent_profile/vm107.research_contrarian_agent.yaml    (Plan 5)
  7. VM107/registry/agent_profile/vm107.research_discovery_agent.yaml     (Plan 5)
  8. VM107/registry/tool/search_macro_research.yaml                       (Plan 5)
  9. VM107/registry/event_type/research_discovery_candidate.yaml          (Plan 5)

Total: 1 data_domain + 5 agent_profile + 1 contract + 1 tool + 1 event_type = 9.

Each must yaml.safe_load + carry impact_on_decision ∈ {HIGH, MEDIUM, LOW}.

RED until Tasks 2 + 3 ship the missing 6 YAMLs.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.phase92


_VM107_ROOT = Path(__file__).resolve().parents[2]


PHASE_92_YAMLS = [
    # Plan 1
    _VM107_ROOT / "registry" / "data_domains" / "research_documents.yaml",
    # Plan 3
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.research_classification_agent.yaml",
    # Plan 4
    _VM107_ROOT / "registry" / "contract" / "phase92_neo4j_schema_extension.yaml",
    # Plan 5 — agents
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.research_summarisation_agent.yaml",
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.research_citation_agent.yaml",
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.research_contrarian_agent.yaml",
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.research_discovery_agent.yaml",
    # Plan 5 — tool
    _VM107_ROOT / "registry" / "tool" / "search_macro_research.yaml",
    # Plan 5 — event_type
    _VM107_ROOT / "registry" / "event_type" / "research_discovery_candidate.yaml",
]


VALID_IMPACT = {"HIGH", "MEDIUM", "LOW"}


@pytest.mark.parametrize("path", PHASE_92_YAMLS, ids=lambda p: p.name)
def test_phase92_yaml_present_and_carries_impact_on_decision(path: Path):
    assert path.exists(), f"missing Phase 92 YAML: {path}"
    payload = yaml.safe_load(path.read_text())
    assert payload is not None, f"empty YAML: {path}"
    impact = payload.get("impact_on_decision")
    assert impact in VALID_IMPACT, (
        f"{path.name}: impact_on_decision={impact!r} not in {VALID_IMPACT}"
    )


def test_phase92_yaml_count_matches_enumerated_manifest():
    """Pin the 9-YAML count so the manifest can't silently shrink."""
    assert len(PHASE_92_YAMLS) == 9, (
        f"Phase 92 YAML manifest must be 9; got {len(PHASE_92_YAMLS)}"
    )
