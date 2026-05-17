"""Phase 47.6 Plan 07 — boot assertion: CAPABILITY_REGISTRY_ROOT env var required.

Tests that initialize_capability_registry() fails loudly without the env var
(no silent defaults — project memory rule + LD-1) and succeeds when it is set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


def test_initialize_fails_without_env(monkeypatch):
    """initialize_capability_registry() raises SystemExit if CAPABILITY_REGISTRY_ROOT unset.

    LD-1: no fallback default. Fail-fast beats silent misconfiguration.
    """
    monkeypatch.delenv("CAPABILITY_REGISTRY_ROOT", raising=False)

    import importlib
    import initialize as init_mod
    importlib.reload(init_mod)

    with pytest.raises(SystemExit) as exc_info:
        init_mod.initialize_capability_registry.__wrapped__()

    assert "CAPABILITY_REGISTRY_ROOT" in str(exc_info.value)


def test_initialize_with_env_succeeds(monkeypatch):
    """initialize_capability_registry() succeeds when CAPABILITY_REGISTRY_ROOT is set."""
    registry_root = str(_VM107_ROOT / "registry")
    monkeypatch.setenv("CAPABILITY_REGISTRY_ROOT", registry_root)

    from core.registry.capability_registry import CapabilityRegistry

    # Reset so we can re-initialize
    CapabilityRegistry._instance = None

    import importlib
    import initialize as init_mod
    importlib.reload(init_mod)

    # Should NOT raise
    init_mod.initialize_capability_registry.__wrapped__()

    # Registry is now initialized
    reg = CapabilityRegistry.get()
    assert len(reg.snapshot.entries) > 0


def test_initialize_idempotent_on_double_call(monkeypatch):
    """initialize_capability_registry() is safe to call when already initialized.

    The underlying CapabilityRegistry raises RuntimeError on double-init,
    but initialize_capability_registry() catches it and continues (since
    some test contexts initialize the registry before calling this function).
    """
    registry_root = str(_VM107_ROOT / "registry")
    monkeypatch.setenv("CAPABILITY_REGISTRY_ROOT", registry_root)

    from core.registry.capability_registry import CapabilityRegistry

    # Initialize once
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(_VM107_ROOT / "registry")

    import importlib
    import initialize as init_mod
    importlib.reload(init_mod)

    # Second call should NOT raise SystemExit (RuntimeError is swallowed)
    init_mod.initialize_capability_registry.__wrapped__()
