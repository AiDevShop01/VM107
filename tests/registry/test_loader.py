"""Tests for CapabilityRegistry loader, lookup, list, and index methods.

Tests:
    test_initialize_full_pipeline: load valid fixtures, get populated registry
    test_lookup_known_id: lookup returns CapabilitySummary for known id
    test_lookup_unknown_id: lookup returns None for unknown id
    test_list_filters: list(type=TOOL, status=REAL) returns only matching
    test_list_stable_order: multiple list() calls return identical sequence
    test_get_index_for_profile: only real+allowed+not-deprecated returned
    test_is_capability_in_scope: True for listed profile, False otherwise
    test_closest_ids: returns top-3 Levenshtein-closest ids for typo
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import (
    CapabilityStatus,
    CapabilityType,
    CapabilitySummary,
)
from core.registry.capability_registry import CapabilityRegistry


@pytest.fixture(autouse=True)
def _reset_registry_singleton():
    """Reset singleton state before and after each test."""
    CapabilityRegistry._instance = None
    yield
    CapabilityRegistry._instance = None


def test_initialize_full_pipeline(valid_registry_root):
    """Loading valid fixture registry returns a populated registry with sorted entries."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    assert len(reg.snapshot.entries) > 0
    # Entries should be sorted by (type, id)
    types_ids = [(e.type.value, e.id) for e in reg.snapshot.entries]
    assert types_ids == sorted(types_ids), "Entries must be sorted by (type, id)"


def test_lookup_known_id(valid_registry_root):
    """lookup('example_tool') returns a CapabilitySummary with correct id."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    result = reg.lookup("example_tool")
    assert result is not None, "lookup('example_tool') should return a CapabilitySummary"
    assert isinstance(result, CapabilitySummary)
    assert result.id == "example_tool"


def test_lookup_unknown_id(valid_registry_root):
    """lookup('nonexistent_id') returns None."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    result = reg.lookup("nonexistent_id_xyz_123")
    assert result is None, "lookup() must return None for unknown ids"


def test_list_filters(valid_registry_root):
    """list(type=TOOL, status=REAL) returns only TOOL entries with REAL status."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    results = reg.list(type=CapabilityType.TOOL, status=CapabilityStatus.REAL)
    for summary in results:
        assert summary.type == CapabilityType.TOOL, f"Expected TOOL, got {summary.type}"
        assert summary.status == CapabilityStatus.REAL, f"Expected REAL, got {summary.status}"


def test_list_stable_order(valid_registry_root):
    """list() returns entries in stable (type, -impact_rank, id) order across calls."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    call1 = [s.id for s in reg.list()]
    call2 = [s.id for s in reg.list()]
    assert call1 == call2, "list() must return identical order on repeated calls"


def test_get_index_for_profile(valid_registry_root):
    """get_index_for_profile returns only real + allowed + not-deprecated entries."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    # example_tool has allowed_agent_profiles=[example_agent]
    index = reg.get_index_for_profile("example_agent")
    # example_tool should be in index
    ids = [item["id"] for item in index]
    assert "example_tool" in ids, (
        f"example_tool should appear in example_agent index, got: {ids}"
    )
    # Each index item must have the required structure
    for item in index:
        assert "id" in item
        assert "short_description" in item
        assert "impact_on_decision" in item
        # All returned entries should be real and not deprecated
        entry = reg.lookup(item["id"])
        assert entry is not None
        assert entry.status == CapabilityStatus.REAL
        assert entry.deprecated is False


def test_is_capability_in_scope(valid_registry_root):
    """is_capability_in_scope returns True for listed profile, False for unlisted."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    # example_tool allows example_agent
    assert reg.is_capability_in_scope("example_agent", "example_tool") is True
    # example_agent (agent_profile) has allowed_agent_profiles=[] (no profile restrictions)
    # so any profile not listed should return False for tools with explicit allowed lists
    assert reg.is_capability_in_scope("unknown_agent", "example_tool") is False


def test_closest_ids(valid_registry_root):
    """closest_ids returns top-3 Levenshtein-closest ids for a typo."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    # "example_toool" is a typo for "example_tool"
    closest = reg.closest_ids("example_toool", limit=3)
    assert isinstance(closest, list)
    assert len(closest) <= 3
    assert "example_tool" in closest, (
        f"'example_tool' should be in closest matches for 'example_toool', got: {closest}"
    )
