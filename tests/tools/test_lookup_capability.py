"""Tests for the lookup_capability meta-tool.

Phase 47.6 Plan 03 — TDD RED suite for lookup_capability.py.

Tests are written BEFORE the implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


@pytest.fixture
def real_registry(tmp_path):
    """Initialize a registry from the real VM107/registry root."""
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


# ---------------------------------------------------------------------------
# Test: lookup of a known id
# ---------------------------------------------------------------------------


def test_known_id(real_registry):
    """lookup("get_trade_quality_score") returns LookupResult(status="ok", capability=...)."""
    from tools.lookup_capability import lookup, LookupResult
    from fingpt_core.contracts.capability_registry import CapabilitySummary

    result = lookup("get_trade_quality_score")

    assert isinstance(result, LookupResult)
    assert result.status == "ok"
    assert result.capability is not None
    assert isinstance(result.capability, CapabilitySummary)
    assert result.capability.id == "get_trade_quality_score"


# ---------------------------------------------------------------------------
# Test: lookup of unknown id returns embedded-status envelope, NOT exception
# ---------------------------------------------------------------------------


def test_unknown_id_envelope(real_registry):
    """lookup("nonexistent") returns not_available envelope, not an exception."""
    from tools.lookup_capability import lookup, LookupResult

    result = lookup("nonexistent")

    assert isinstance(result, LookupResult)
    assert result.status == "not_available"
    assert result.capability is None
    # meta must carry the attempted id and closest matches
    assert result.meta.get("capability_id_attempted") == "nonexistent"
    assert "closest_matches" in result.meta
    assert isinstance(result.meta["closest_matches"], list)


# ---------------------------------------------------------------------------
# Test: list_capabilities filters compose
# ---------------------------------------------------------------------------


def test_list_filters_compose(real_registry):
    """list_capabilities(type="tool", status="real") returns only tool/real entries."""
    from tools.lookup_capability import list_capabilities, ListResult
    from fingpt_core.contracts.capability_registry import CapabilitySummary

    result = list_capabilities(type="tool", status="real")

    assert isinstance(result, ListResult)
    assert result.status == "ok"
    assert all(
        c.type.value == "tool" and c.status.value == "real"
        for c in result.capabilities
    )
    assert result.returned_count == len(result.capabilities)
    assert len(result.capabilities) > 0


# ---------------------------------------------------------------------------
# Test: list_capabilities stable order
# ---------------------------------------------------------------------------


def test_list_stable_order(real_registry):
    """Same list() call invoked twice returns identical sequence."""
    from tools.lookup_capability import list_capabilities

    result1 = list_capabilities(type="tool", status="real")
    result2 = list_capabilities(type="tool", status="real")

    ids1 = [c.id for c in result1.capabilities]
    ids2 = [c.id for c in result2.capabilities]
    assert ids1 == ids2


# ---------------------------------------------------------------------------
# Test: lookup stub id returns CapabilitySummary (tool does NOT refuse)
# ---------------------------------------------------------------------------


def test_lookup_stub_returns_summary(real_registry):
    """lookup(stub_id) returns the CapabilitySummary; the tool itself does NOT refuse."""
    from tools.lookup_capability import lookup, LookupResult
    from fingpt_core.contracts.capability_registry import CapabilitySummary

    # Find a stub id in the real registry
    reg = real_registry
    stub_entries = [e for e in reg.snapshot.entries if e.status.value == "stub"]
    if not stub_entries:
        pytest.skip("No stub capabilities in registry; test not applicable")

    stub_id = stub_entries[0].id
    result = lookup(stub_id)

    assert isinstance(result, LookupResult)
    assert result.status == "ok"
    assert result.capability is not None
    assert isinstance(result.capability, CapabilitySummary)
    assert result.capability.status.value == "stub"


# ---------------------------------------------------------------------------
# Test: discovery_reason is logged (via mocked envelope_context)
# ---------------------------------------------------------------------------


def test_discovery_reason_logged(real_registry):
    """lookup(id, discovery_reason=...) constructs an introspection event."""
    from tools.lookup_capability import lookup

    mock_envelope = MagicMock()
    mock_envelope.reasoning_context_id = "test-ctx-001"

    with patch("core.agents.envelope_context.current_envelope") as mock_cv:
        mock_cv.get.return_value = mock_envelope
        result = lookup(
            "get_trade_quality_score",
            discovery_reason="missing_param_understanding",
        )

    assert result.status == "ok"
    # No exception raised — introspection logging ran without crashing


# ---------------------------------------------------------------------------
# Test: no crash when no envelope active (CLI context)
# ---------------------------------------------------------------------------


def test_no_introspection_outside_envelope(real_registry):
    """Calling lookup() with no current_envelope does NOT crash."""
    from tools.lookup_capability import lookup

    with patch("core.agents.envelope_context.current_envelope") as mock_cv:
        mock_cv.get.return_value = None
        result = lookup("get_trade_quality_score")

    assert result.status == "ok"
