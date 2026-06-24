"""Phase 89.2 Wave 0 — discovery agent module scaffolding tests (REQ-89.2-1).

These tests target the MacroRelationshipDiscovery agent module that Phase 89.2
Plan 03 will introduce at `agents.macro_relationship_discovery.agent`. All
tests in this file are xfail stubs at Wave 0 — they exist only so Wave 1+
tasks have a real test target to point their `<automated>` verify commands
at (Nyquist compliance: no Wave 1+ task can run without a pre-existing test).

The import is wrapped in try/except ImportError so `pytest --co` (collect-only)
remains green before Plan 03 lands. Once Plan 03 produces the module, these
xfails will start passing and the strict=False marker keeps the suite green
until the body of each test is flipped to real assertions in Plan 03 / Plan 07.

Per project locks:
  - No `pytest.importorskip` — Plan 03 needs the import to hard-fail once the
    module is *supposed* to exist (we want the xfail→xpass transition to be
    a real signal, not a silent skip).
  - No live VM102 / Postgres / Neo4j — every dependency is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase89


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 03 — agent module not yet implemented",
    strict=False,
)
def test_run_returns_correct_shape():
    """MacroRelationshipDiscovery.run() returns the documented dict shape.

    Expected keys (per Phase 89.2 RESEARCH + VALIDATION):
      - proposals_created: int
      - scan_duration_s: float
      - throughput_action: str (one of {"ok", "warned_low", "tightened"})
    """
    try:
        from agents.macro_relationship_discovery.agent import (
            MacroRelationshipDiscovery,
        )
    except ImportError:
        pytest.xfail("agents.macro_relationship_discovery.agent not yet implemented")
        return

    agent = MacroRelationshipDiscovery()
    result = agent.run(message="smoke", run_mode="manual")

    assert isinstance(result, dict)
    assert set(result.keys()) >= {"proposals_created", "scan_duration_s", "throughput_action"}
    assert isinstance(result["proposals_created"], int)
    assert isinstance(result["scan_duration_s"], float)
    assert isinstance(result["throughput_action"], str)


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 03 — Vm102DiscoveryClient wiring not yet implemented",
    strict=False,
)
def test_run_calls_vm102_client():
    """Agent.run() calls Vm102DiscoveryClient.{indicator_correlations,indicator_lead_lag}.

    Asserted via mock: at least one (indicator, asset) pair from DEFAULT_SCAN_PAIRS
    triggers both method calls.
    """
    try:
        from agents.macro_relationship_discovery import agent as agent_mod
    except ImportError:
        pytest.xfail("agents.macro_relationship_discovery.agent not yet implemented")
        return

    with patch.object(agent_mod, "Vm102DiscoveryClient") as MockClient:
        instance = MagicMock()
        instance.indicator_correlations.return_value = {
            "r": 0.05,
            "p_value": 0.7,
            "sample_size": 48,
            "period_start": "2023-01-01",
            "period_end": "2024-12-31",
        }
        instance.indicator_lead_lag.return_value = {
            "peak_lag": 0.0,
            "peak_r": 0.05,
            "p_value": 0.7,
        }
        MockClient.return_value = instance

        agent = agent_mod.MacroRelationshipDiscovery()
        agent.run(message="smoke", run_mode="manual")

    assert instance.indicator_correlations.call_count >= 1, (
        "Vm102DiscoveryClient.indicator_correlations must be called for at least "
        "one (indicator, asset) pair from DEFAULT_SCAN_PAIRS"
    )
    assert instance.indicator_lead_lag.call_count >= 1, (
        "Vm102DiscoveryClient.indicator_lead_lag must be called for at least "
        "one (indicator, asset) pair from DEFAULT_SCAN_PAIRS"
    )


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 03 — throughput governor wiring not yet implemented",
    strict=False,
)
def test_throughput_action_enum():
    """throughput_action returned by run() is always in {"ok", "warned_low", "tightened"}.

    Asserts across at least one mocked run scenario; Plan 03 expands to the
    full enum coverage matrix (under/over thresholds) once the governor is
    wired into the agent's run loop.
    """
    try:
        from agents.macro_relationship_discovery import agent as agent_mod
    except ImportError:
        pytest.xfail("agents.macro_relationship_discovery.agent not yet implemented")
        return

    valid_actions = {"ok", "warned_low", "tightened"}

    with patch.object(agent_mod, "Vm102DiscoveryClient") as MockClient:
        client_instance = MagicMock()
        client_instance.indicator_correlations.return_value = {
            "r": 0.05,
            "p_value": 0.7,
            "sample_size": 48,
            "period_start": "2023-01-01",
            "period_end": "2024-12-31",
        }
        client_instance.indicator_lead_lag.return_value = {
            "peak_lag": 0.0,
            "peak_r": 0.05,
            "p_value": 0.7,
        }
        MockClient.return_value = client_instance

        agent = agent_mod.MacroRelationshipDiscovery()
        result = agent.run(message="smoke", run_mode="manual")

    assert result["throughput_action"] in valid_actions, (
        f"throughput_action must be one of {valid_actions}, "
        f"got {result['throughput_action']!r}"
    )
