"""Phase 87 REQ-87-6c — Brain B6 contract YAML registered + discoverable.

Per REQ-87-6 (final acceptance):
    capability registry contract YAML `episodic_memory_service` discoverable
    via `lookup_capability`.

This is the targeted, REQ-87-6c-only test. The wider sweep lives in
test_capability_registry_sweep.py.

The on-disk YAML lives at:
    VM107/registry/contract/episodic_memory_service.yaml

(Plus a service YAML at VM107/registry/service/episodic_memory_service.yaml
for the deployed service binding.)

The contract YAML must declare:
  - id: episodic_memory_service
  - type: contract
  - hard_scoped: true (B6 is reasoning-critical — HIGH impact_on_decision)
  - allowed_agent_profiles: includes the three Phase 87 macro analyst agents
    (transmission_analyst, regime_analyst, story_tracker)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.phase_87

VM107_ROOT = Path(__file__).resolve().parents[2]
B6_CONTRACT_PATH = VM107_ROOT / "registry" / "contract" / "episodic_memory_service.yaml"


def test_b6_contract_yaml_on_disk() -> None:
    """REQ-87-6c — the B6 contract YAML lives at the expected path."""
    assert B6_CONTRACT_PATH.exists(), (
        f"REQ-87-6c — episodic_memory_service contract YAML missing at "
        f"{B6_CONTRACT_PATH}. Wave 4a Plan 87-07 register-on-ship lock "
        "violated."
    )


def test_b6_contract_yaml_parses() -> None:
    doc = yaml.safe_load(B6_CONTRACT_PATH.read_text())
    assert isinstance(doc, dict), "B6 contract YAML did not parse to a dict"
    assert doc["id"] == "episodic_memory_service"
    assert doc["type"] == "contract"
    # B6 RAG sits in front of every macro narrative LLM prompt → HIGH
    assert doc["impact_on_decision"] == "HIGH"
    assert doc["hard_scoped"] is True
    # All three macro analysts that use B6 RAG (per LOCK-6) must appear in the
    # allow-list — this is the gate that lookup_capability scope checks rely on.
    allowed = set(doc.get("allowed_agent_profiles") or [])
    required = {
        "vm107.macro_transmission_analyst",
        "vm107.macro_regime_analyst",
        "vm107.macro_story_tracker",
    }
    missing = required - allowed
    assert not missing, (
        f"REQ-87-6c — B6 contract missing macro analyst profiles in "
        f"allowed_agent_profiles: {sorted(missing)}"
    )
