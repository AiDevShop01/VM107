"""Phase 70.5 Plan 07 — shared fixtures for proxy tool tests.

Provides:
- mock_vm_base_urls      — sets all four BASE_URL env vars to test stubs via monkeypatch
- unset_vm_base_urls     — removes all four BASE_URL env vars (for fail-fast tests)
- mock_dispatcher_ctx    — top-level InvocationContext (depth=0, no parent)
- ALL_PROXY_MODULE_PATHS — list of all 16 proxy module importable paths
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# Ensure VM107 root is on sys.path
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# Env var names used by each VM client
# ---------------------------------------------------------------------------

_VM_ENV_VARS: dict[str, str] = {
    "VM100_API_URL": "http://test-vm100/",
    "VM101_API_URL": "http://test-vm101/",
    "VM102_API_URL": "http://test-vm102/",
    "VM107_API_URL": "http://test-vm107/",
}

# ---------------------------------------------------------------------------
# All 16 proxy module importable paths (relative to VM107 root)
# ---------------------------------------------------------------------------

ALL_PROXY_MODULE_PATHS: list[str] = [
    "tools.proxies.vm100_analytics_calendar",
    "tools.proxies.vm100_behavioral_edges_for_execution",
    "tools.proxies.vm100_ws_mission_control",
    "tools.proxies.vm101_ribbon_bars",
    "tools.proxies.vm101_ribbon_quotes",
    "tools.proxies.vm102_regime_current",
    "tools.proxies.vm102_risk_metrics_snapshot",
    "tools.proxies.vm102_structural_events",
    "tools.proxies.vm107_intelligence_feed_discoveries",
    "tools.proxies.vm107_intelligence_feed_macro",
    "tools.proxies.vm107_mcp_server",
    "tools.proxies.vm107_morning_brief",
    "tools.proxies.vm107_narratives_global",
    "tools.proxies.vm107_opportunities_ranked",
    "tools.proxies.vm107_overnight_delta",
    "tools.proxies.vm107_reflection_prompt",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_vm_base_urls(monkeypatch):
    """Set all four VM BASE_URL / API_URL env vars to test stubs.

    Used by all proxy invocation tests to ensure env is present.
    Also sets legacy VM100_BASE_URL / VM101_BASE_URL for cross-client compat.
    """
    for key, val in _VM_ENV_VARS.items():
        monkeypatch.setenv(key, val)
    # Also set BASE_URL variants used in the plan spec for fail-fast tests
    monkeypatch.setenv("VM100_BASE_URL", "http://test-vm100/")
    monkeypatch.setenv("VM101_BASE_URL", "http://test-vm101/")
    monkeypatch.setenv("VM102_BASE_URL", "http://test-vm102/")
    monkeypatch.setenv("VM107_BASE_URL", "http://test-vm107/")
    return _VM_ENV_VARS


@pytest.fixture
def unset_vm_base_urls(monkeypatch):
    """Remove all VM BASE_URL / API_URL env vars (for fail-fast tests)."""
    for key in _VM_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("VM100_BASE_URL", raising=False)
    monkeypatch.delenv("VM101_BASE_URL", raising=False)
    monkeypatch.delenv("VM102_BASE_URL", raising=False)
    monkeypatch.delenv("VM107_BASE_URL", raising=False)
    return None


@pytest.fixture
def mock_dispatcher_ctx():
    """Top-level InvocationContext (depth=0, no parent) for proxy dispatch tests."""
    from fingpt_core.contracts.invocation_context import InvocationContext

    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        conversation_id=None,
        execution_depth=0,
    )
