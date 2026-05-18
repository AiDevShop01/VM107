"""Phase 48 Plan 48-03 Task 3.2 — snapshot freeze idempotency + property access.

Implements REQ-48-D15.

Asserts:
- freeze_snapshot_hash(loop_id) reads CapabilityRegistry.get().snapshot_hash
  (PROPERTY access — Wave 0 finding 3, CONTEXT § Decision 15 named it
  current_snapshot_hash() which does NOT exist).
- First call writes the hash to refinement_loops doc.
- Second call returns the recorded hash WITHOUT re-fetching the property
  (idempotent — even if the registry property changes, the loop's frozen
  value is preserved).
"""
from __future__ import annotations

import pytest


def test_freeze_snapshot_hash_writes_property_value_on_first_call(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import snapshot_freeze, state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )
    monkeypatch.setattr(
        snapshot_freeze.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-freeze-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-fr-1",
    )

    # initialize_loop_state already freezes; calling freeze_snapshot_hash
    # again must be idempotent and return the recorded value.
    h = snapshot_freeze.freeze_snapshot_hash(mongo_test_db, "loop-freeze-1")
    assert h == frozen_registry_snapshot_hash


def test_freeze_snapshot_hash_idempotent_when_property_changes(
    mongo_test_db, valid_hypothesis_id, monkeypatch
):
    """Second call returns the FROZEN value, ignoring registry mutation."""
    from core.agents.refinement_orchestrator import snapshot_freeze, state as state_mod

    class _FakeRegV1:
        snapshot_hash = "snapshot-v1"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV1())
    )
    monkeypatch.setattr(
        snapshot_freeze.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV1())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-freeze-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-fr-2",
    )

    # Now mutate the registry property side-channel.
    class _FakeRegV2:
        snapshot_hash = "snapshot-v2-CHANGED"

    monkeypatch.setattr(
        snapshot_freeze.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV2())
    )

    # Second call must return the originally-frozen value.
    h2 = snapshot_freeze.freeze_snapshot_hash(mongo_test_db, "loop-freeze-2")
    assert h2 == "snapshot-v1"


def test_freeze_snapshot_hash_uses_property_access_not_method(monkeypatch):
    """Static check: snapshot_freeze.py uses .snapshot_hash (property)."""
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    src = (repo_root / "core" / "agents" / "refinement_orchestrator" / "snapshot_freeze.py").read_text()

    # Property access pattern from the plan's must_haves key_links:
    assert re.search(r"CapabilityRegistry\.get\(\)\.snapshot_hash", src), (
        "snapshot_freeze.py must read CapabilityRegistry.get().snapshot_hash (property)"
    )
    # Must NOT call current_snapshot_hash() — that method does not exist.
    assert "current_snapshot_hash" not in src, (
        "snapshot_freeze.py must not reference the non-existent current_snapshot_hash method"
    )
