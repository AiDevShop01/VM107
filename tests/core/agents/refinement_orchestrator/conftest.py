"""Phase 48 shared fixture factories for refinement_orchestrator tests.

Real implementations, not placeholders. The fixture SURFACE (name, signature,
return shape) is locked here in Plan 00 / Wave 0 so Wave 1+ tests — especially
the Plan 08b E2E goldens — can be written against it without scavenger-hunting.

Some fixture bodies reference modules that haven't shipped yet
(`core.events.phase56_client.emit_event` lands in Plan 03; the full
`CapabilityRegistry.get().snapshot_hash` monkeypatch target is consumed in
Plan 03+). Where that's the case, the fixture either:
  1. Returns a canonical mock / constant that downstream tests use directly, or
  2. Documents the deferred monkeypatch.setattr target in a comment — the
     downstream test applies the patch itself once the module is importable.

This keeps Plan 00 dependency-free while still locking the fixture contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock factories for the 6 typed wrappers from core.agents.invocation
# (run_idea + run_strategy already shipped; the other 4 land in Plan 01).
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_typed_wrappers():
    """Mock factory for the 6 typed wrappers consumed by the orchestrator.

    Returns a dict mapping wrapper name -> MagicMock. Downstream tests
    apply `monkeypatch.setattr("core.agents.invocation.<name>", mock)`
    themselves once the orchestrator imports the wrapper module.

    Surface locked here so Plan 02 / 03 / 08b tests share the same names.
    """
    return {
        "run_idea": MagicMock(name="run_idea"),
        "run_strategy": MagicMock(name="run_strategy"),
        "run_code": MagicMock(name="run_code"),
        "run_build": MagicMock(name="run_build"),
        "run_backtest": MagicMock(name="run_backtest"),
        "run_critic": MagicMock(name="run_critic"),
    }


# ---------------------------------------------------------------------------
# Phase 56 event emission mock (captures all .emit_event call_args_list).
# Plan 03 ships core.events.phase56_client.emit_event; until then this
# fixture surfaces the canonical mock so E2E goldens can write against it.
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_emit_event(monkeypatch):
    """Mock for phase56_client.emit_event that captures call_args_list.

    Downstream tests apply:
        monkeypatch.setattr(
            "core.events.phase56_client.emit_event", mock_emit_event
        )
    once Plan 03 has shipped the module. The fixture itself just provides
    the canonical MagicMock so assertions on payload shape are consistent
    across the suite.
    """
    return MagicMock(name="emit_event")


# ---------------------------------------------------------------------------
# Mongo test database (mongomock-backed). Used by RefinementLoopState
# persistence tests + accepted/rejected WORM collection tests.
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo_test_db():
    """Mongomock-backed test database for Mongo-round-trip tests.

    Skips the test cleanly when mongomock isn't installed in the active
    environment (e.g., minimal CI shards) instead of importing at module
    level and failing collection on every test.
    """
    pytest.importorskip("mongomock")
    import mongomock

    client = mongomock.MongoClient()
    return client["fingpt_phase48_test"]


# ---------------------------------------------------------------------------
# Frozen CapabilityRegistry snapshot hash. Plan 03 wires the real
# monkeypatch into the orchestrator's snapshot-freeze path. This fixture
# surfaces the canonical test value so every test agrees on the hash.
# ---------------------------------------------------------------------------

@pytest.fixture
def frozen_registry_snapshot_hash():
    """Canonical deterministic snapshot hash used by Phase 48 tests.

    Downstream tests apply:
        monkeypatch.setattr(
            CapabilityRegistry,
            "snapshot_hash",
            property(lambda self: frozen_registry_snapshot_hash),
        )
    or equivalent, depending on access pattern. The fixture provides the
    hash string so all tests pin to the same value.

    NOTE: this is the corrected property-access pattern per Wave 0
    verification finding 3 (CONTEXT.md § Decision 15 named it
    `current_snapshot_hash()` — that method does NOT exist; the real
    API is `CapabilityRegistry.get().snapshot_hash`).
    """
    return "phase48-test-snapshot-deadbeef"


# ---------------------------------------------------------------------------
# Valid Hypothesis fixture. Inserts a minimal valid Hypothesis doc into
# the test Mongo and returns its id. Used by every loop-entry-contract
# test + every E2E golden.
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_hypothesis_id(mongo_test_db):
    """Minimal valid Hypothesis persisted to mongomock; returns _id.

    Phase 48 enforces a Hypothesis-id-in entry contract (CONTEXT § Decision 6).
    Every refinement loop test needs a real id that resolves against the
    `hypotheses` collection. This fixture creates the minimum viable doc
    so downstream tests don't each re-roll their own.
    """
    hyp_id = "hyp_phase48_test_001"
    mongo_test_db["hypotheses"].insert_one(
        {
            "_id": hyp_id,
            "schema_version": 1,
            "title": "Phase 48 test hypothesis",
            "core_idea": "test placeholder — replace per-test if needed",
        }
    )
    return hyp_id
