"""Tests for CapabilityRegistry singleton behavior.

Tests:
    test_double_init_fails: second initialize() call raises RuntimeError
    test_get_before_init: get() before initialize raises with actionable message
    test_initialize_freezes_snapshot: snapshot.entries is tuple (immutable)
"""

from __future__ import annotations

import pytest

from core.registry.capability_registry import CapabilityRegistry


@pytest.fixture(autouse=True)
def _reset_registry_singleton():
    """Reset singleton state before and after each test to prevent leakage."""
    CapabilityRegistry._instance = None
    yield
    CapabilityRegistry._instance = None


def test_double_init_fails(valid_registry_root):
    """Calling initialize() twice must raise RuntimeError with 'already initialized'."""
    CapabilityRegistry.initialize(valid_registry_root)
    with pytest.raises(RuntimeError) as exc_info:
        CapabilityRegistry.initialize(valid_registry_root)
    assert "already initialized" in str(exc_info.value).lower()


def test_get_before_init():
    """Calling get() before initialize() must raise RuntimeError with actionable message."""
    with pytest.raises(RuntimeError) as exc_info:
        CapabilityRegistry.get()
    msg = str(exc_info.value)
    assert "initialize" in msg.lower(), (
        f"Error message should mention 'initialize', got: {msg!r}"
    )


def test_initialize_freezes_snapshot(valid_registry_root):
    """After initialize(), snapshot.entries must be a tuple (not a mutable list)."""
    reg = CapabilityRegistry.initialize(valid_registry_root)
    assert isinstance(reg.snapshot.entries, tuple), (
        f"snapshot.entries must be tuple, got {type(reg.snapshot.entries)}"
    )
