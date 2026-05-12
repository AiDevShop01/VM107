"""Tests for Phase 60 agent_profile registry YAMLs — CTX-§13.

Replaces the Wave 0 skip stub (Plan 60-01) with real test bodies.

CTX-§13: All new registry/agent_profile/ YAMLs must exist and parse correctly.

Wave 1 acceptance: directory exists (may be empty + .gitkeep).
Wave 2+ tightens: each *.yaml must parse with required fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import yaml

REGISTRY_AGENT_PROFILE = _VM107_ROOT / "registry" / "agent_profile"


def test_all_agent_profile_yamls_parse():
    """CTX-§13 — every YAML in registry/agent_profile/ must parse cleanly.

    Wave 1 acceptance: directory exists (may be empty + .gitkeep).
    Wave 2+ tightens: each *.yaml must parse with required fields.
    """
    assert REGISTRY_AGENT_PROFILE.is_dir(), (
        f"registry/agent_profile/ directory missing at {REGISTRY_AGENT_PROFILE}"
    )
    yaml_files = sorted(REGISTRY_AGENT_PROFILE.glob("*.yaml"))
    # Wave 1 may have 0 yaml files (just .gitkeep); Waves 2-5 add 9+
    for yf in yaml_files:
        data = yaml.safe_load(yf.read_text())
        assert isinstance(data, dict), f"{yf} did not parse to dict"
        assert data.get("type") == "agent_profile", f"{yf} missing/wrong type"
        for required in ["id", "name", "description", "version", "phase", "status"]:
            assert required in data, f"{yf} missing {required}"
