"""Phase 70.5 Plan 07 — TDD Wave 0: fail-fast tests for env-driven VM clients.

Each VM client MUST raise RuntimeError (or KeyError) when its BASE_URL / API_URL
env var is unset. No fallback defaults allowed (memory rule: feedback_env_driven_no_fallbacks).

Tests:
1. VM100Client — raises RuntimeError when VM100_API_URL unset
2. VM101Client — raises RuntimeError when VM101_API_URL unset
3. VM102Client — raises RuntimeError when VM102_API_URL unset
4. VM107 proxy client — raises RuntimeError when VM107_API_URL unset
5. Each proxy module run_async raises RuntimeError before HTTP when env missing
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio  # noqa: F401 — ensure async plugin active

# Ensure VM107 root is on sys.path
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# 1. VM100Client — raises RuntimeError when env var unset
# ---------------------------------------------------------------------------


def test_vm100_client_raises_when_env_unset(unset_vm_base_urls):
    """VM100Client() must raise RuntimeError when VM100_API_URL is missing."""
    from fingpt_core.clients.vm100_client import VM100Client

    with pytest.raises(RuntimeError, match="VM100_API_URL"):
        VM100Client()


def test_vm100_client_constructs_when_env_set(mock_vm_base_urls):
    """VM100Client() constructs cleanly when VM100_API_URL is present."""
    from fingpt_core.clients.vm100_client import VM100Client

    client = VM100Client()
    assert "test-vm100" in client.base_url


# ---------------------------------------------------------------------------
# 2. VM101Client — raises RuntimeError when env var unset
# ---------------------------------------------------------------------------


def test_vm101_client_raises_when_env_unset(unset_vm_base_urls):
    """VM101Client() must raise RuntimeError when VM101_API_URL is missing."""
    from fingpt_core.clients.vm101_client import VM101Client

    with pytest.raises(RuntimeError, match="VM101_API_URL"):
        VM101Client()


def test_vm101_client_constructs_when_env_set(mock_vm_base_urls):
    """VM101Client() constructs cleanly when VM101_API_URL is present."""
    from fingpt_core.clients.vm101_client import VM101Client

    client = VM101Client()
    assert "test-vm101" in client.base_url


# ---------------------------------------------------------------------------
# 3. VM102Client — raises RuntimeError when env var unset
# ---------------------------------------------------------------------------


def test_vm102_client_raises_when_env_unset(unset_vm_base_urls):
    """VM102Client() must raise RuntimeError when VM102_API_URL is missing."""
    from fingpt_core.clients.vm102_client import VM102Client

    with pytest.raises(RuntimeError, match="VM102_API_URL"):
        VM102Client()


def test_vm102_client_constructs_when_env_set(mock_vm_base_urls):
    """VM102Client() constructs cleanly when VM102_API_URL is present."""
    from fingpt_core.clients.vm102_client import VM102Client

    client = VM102Client()
    assert "test-vm102" in client.base_url


# ---------------------------------------------------------------------------
# 4. VM107 proxy tools — proxy VM client raises RuntimeError when env unset
# ---------------------------------------------------------------------------


def test_vm107_proxy_client_raises_when_env_unset(unset_vm_base_urls):
    """VM107 self-proxy tools must raise RuntimeError when VM107_API_URL is missing.

    VM107 proxy tools (vm107.*) use a dedicated VM107SelfClient that reads
    VM107_API_URL from the environment. No fallback allowed.
    """
    from tools.proxies.vm107_intelligence_feed_macro import Vm107Client

    with pytest.raises(RuntimeError, match="VM107_API_URL"):
        Vm107Client()


def test_vm107_proxy_client_constructs_when_env_set(mock_vm_base_urls):
    """VM107 self-proxy client constructs cleanly when VM107_API_URL is present."""
    from tools.proxies.vm107_intelligence_feed_macro import Vm107Client

    client = Vm107Client()
    assert "test-vm107" in client.base_url


# ---------------------------------------------------------------------------
# 5. Parametrize each proxy module: run_async raises RuntimeError before HTTP
#    when env var is unset
# ---------------------------------------------------------------------------

_ALL_PROXY_MODULES = [
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


@pytest.mark.parametrize("module_path", _ALL_PROXY_MODULES)
@pytest.mark.asyncio
async def test_proxy_run_async_raises_when_env_unset(module_path, unset_vm_base_urls):
    """Each proxy run_async must raise RuntimeError before any HTTP call when env missing."""
    mod = importlib.import_module(module_path)

    # Should raise RuntimeError during client construction (before HTTP)
    with pytest.raises(RuntimeError):
        await mod.run_async()
