"""Phase 47.6 Plan 07 — boot assertion: hard-fail on invalid registry (stages 1-7).

Tests that initialize_capability_registry() raises SystemExit for each of the
7 invalid fixture trees, and succeeds for the valid fixture tree.

Fixtures are the same ones created in Plan 02 (tests/registry/fixtures/).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_FIXTURES_DIR = _VM107_ROOT / "tests" / "registry" / "fixtures"


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5, 6, 7])
def test_initialize_fails_on_invalid_stage(stage: int, monkeypatch):
    """initialize_capability_registry() raises SystemExit for each invalid_stage_N fixture.

    LD-2 hard-fail: any registry validation failure must prevent VM107 startup.
    """
    fixture_root = _FIXTURES_DIR / f"invalid_stage_{stage}"

    if not fixture_root.exists():
        pytest.skip(f"Fixture invalid_stage_{stage} not found — skipping")

    monkeypatch.setenv("CAPABILITY_REGISTRY_ROOT", str(fixture_root))

    from core.registry.capability_registry import CapabilityRegistry
    CapabilityRegistry._instance = None

    import importlib
    import initialize as init_mod
    importlib.reload(init_mod)

    with pytest.raises(SystemExit) as exc_info:
        init_mod.initialize_capability_registry.__wrapped__()

    # Error message should mention CapabilityRegistry validation failure
    error_msg = str(exc_info.value)
    assert "CapabilityRegistry" in error_msg or "CAPABILITY_REGISTRY_ROOT" in error_msg, (
        f"Stage {stage} SystemExit message is not informative: {error_msg!r}"
    )


def test_initialize_succeeds_on_valid_fixture(monkeypatch):
    """initialize_capability_registry() succeeds with the valid fixture tree."""
    valid_root = _FIXTURES_DIR / "valid"

    if not valid_root.exists():
        pytest.skip("Fixture valid/ not found — skipping")

    monkeypatch.setenv("CAPABILITY_REGISTRY_ROOT", str(valid_root))

    from core.registry.capability_registry import CapabilityRegistry
    CapabilityRegistry._instance = None

    import importlib
    import initialize as init_mod
    importlib.reload(init_mod)

    # Should NOT raise
    init_mod.initialize_capability_registry.__wrapped__()

    # Registry should be initialized and non-empty
    reg = CapabilityRegistry.get()
    assert len(reg.snapshot.entries) > 0
    assert len(reg.snapshot.snapshot_hash) == 64  # SHA-256 hex
