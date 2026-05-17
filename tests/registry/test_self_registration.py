"""Self-registration test — lookup_capability.yaml dogfood test.

Verifies that the lookup_capability tool registers itself through all 7 validation
stages, and that the registry can describe its own meta-tool.

Phase 47.6 Plan 03 — TDD RED.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


# ---------------------------------------------------------------------------
# Test: lookup_capability.yaml loads through all 7 validation stages
# ---------------------------------------------------------------------------


def test_lookup_capability_yaml_loads():
    """CapabilityRegistry.initialize() must succeed with the real registry root.

    The lookup_capability.yaml self-validates through all 7 stages (dogfood).
    """
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    reg = CapabilityRegistry.initialize(registry_root)

    # If we got here without an exception, all 7 stages passed
    assert reg is not None
    assert reg.snapshot.entry_count >= 152


# ---------------------------------------------------------------------------
# Test: lookup_capability is invokable after initialize
# ---------------------------------------------------------------------------


def test_lookup_capability_is_invokable():
    """After initialize, reg.lookup("lookup_capability") returns a CapabilitySummary."""
    from core.registry.capability_registry import CapabilityRegistry
    from fingpt_core.contracts.capability_registry import CapabilitySummary, ImpactLevel

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    reg = CapabilityRegistry.get()

    summary = reg.lookup("lookup_capability")
    assert summary is not None
    assert isinstance(summary, CapabilitySummary)
    assert summary.id == "lookup_capability"
    assert summary.status.value == "real"
    assert summary.impact_on_decision == ImpactLevel.HIGH


# ---------------------------------------------------------------------------
# Test: lookup_capability allowed_agent_profiles contains all 15 profiles
# ---------------------------------------------------------------------------

_EXPECTED_PROFILES = {
    "agent_zero",
    "idea_agent",
    "strategy_agent",
    "trade_auditor_agent",
    "trade_auditor_agent._reader",
    "trade_auditor_agent._analyzer",
    "trade_auditor_agent._writer",
    "behavioral_mentor_agent",
    "behavioral_mentor_agent._reader",
    "behavioral_mentor_agent._analyzer",
    "behavioral_mentor_agent._writer",
    "weekly_review_agent",
    "weekly_review_agent._reader",
    "weekly_review_agent._analyzer",
    "weekly_review_agent._writer",
}


def test_lookup_capability_allowed_profiles():
    """lookup_capability must be allowed for all 15 profiles (6 parents + 9 dotted)."""
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    reg = CapabilityRegistry.get()

    summary = reg.lookup("lookup_capability")
    assert summary is not None

    allowed_set = set(summary.allowed_agent_profiles)
    assert _EXPECTED_PROFILES == allowed_set, (
        f"Missing profiles: {_EXPECTED_PROFILES - allowed_set}\n"
        f"Extra profiles: {allowed_set - _EXPECTED_PROFILES}"
    )
