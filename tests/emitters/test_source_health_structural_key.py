"""SC-5 / D-03 proof: SourceHealthRegistry per-context isolation is STRUCTURAL.

Phase 172 Plan 03. Mirrors the 135-06 object-carried immutable-key pattern:
a frozen ``SourceHealthKey(subsystem, ctxid)`` carries the composed key so a
caller cannot construct a context-scoped report without a ctxid, and two
distinct contexts can never last-write-wins-collide onto one bare key.

Uses an ISOLATED ``SourceHealthRegistry()`` (not the shared singleton) so the
assertions are hermetic — matching the isolated-registry convention in
``tests/emitters/test_overnight_delta_emitter.py``.
"""
import pytest

from emitters.source_health_registry import SourceHealthKey, SourceHealthRegistry


def test_two_distinct_ctxids_produce_two_snapshot_entries():
    """Two SourceHealthKeys (same subsystem, different ctxid) reported on one
    registry yield TWO separate snapshot() entries — the second write does NOT
    mask the first (the last-write-wins race the 135-06 pattern closes)."""
    reg = SourceHealthRegistry()

    reg.report(SourceHealthKey("qdrant", "ctx-A"), available=True)
    reg.report(SourceHealthKey("qdrant", "ctx-B"), available=False, failure_reason="RuntimeError")

    snap = reg.snapshot()
    assert "qdrant:ctx-A" in snap
    assert "qdrant:ctx-B" in snap
    # No collision: each context keeps its own health, independent of write order.
    assert snap["qdrant:ctx-A"].available is True
    assert snap["qdrant:ctx-B"].available is False
    assert snap["qdrant:ctx-B"].failure_reason == "RuntimeError"


def test_empty_ctxid_raises_value_error():
    """A scoped report cannot be built without a ctxid — structural enforcement."""
    with pytest.raises(ValueError):
        SourceHealthKey("qdrant", "")


def test_empty_subsystem_raises_value_error():
    """A scoped key also requires a subsystem."""
    with pytest.raises(ValueError):
        SourceHealthKey("", "ctx-A")


def test_key_property_matches_historical_convention():
    """.key reproduces the exact f-string convention existing readers match."""
    assert SourceHealthKey("qdrant", "abc").key == "qdrant:abc"
    assert SourceHealthKey("embedding", "abc").key == "embedding:abc"


def test_bare_string_report_coexists_with_scoped_report():
    """A bare-string report('vm100', True) and a scoped report coexist without
    collision — the ~60 bare-string emitter callers remain unbroken."""
    reg = SourceHealthRegistry()

    reg.report("vm100", available=True)
    reg.report(SourceHealthKey("qdrant", "ctx-A"), available=True)

    snap = reg.snapshot()
    assert snap["vm100"].available is True
    assert snap["vm100"].source_id == "vm100"
    assert snap["qdrant:ctx-A"].available is True
    # Bare and scoped live side by side — three distinct keys, no masking.
    assert set(snap) == {"vm100", "qdrant:ctx-A"}


def test_report_stores_scoped_health_under_composed_key():
    """report(SourceHealthKey(...)) records under the deterministic .key string,
    with source_id set to that composed key (snapshot stays dict[str, SourceHealth])."""
    reg = SourceHealthRegistry()

    reg.report(SourceHealthKey("qdrant", "ctx-A"), available=False, failure_reason="ConnectError")

    entry = reg.snapshot()["qdrant:ctx-A"]
    assert entry.source_id == "qdrant:ctx-A"
    assert entry.available is False
    assert entry.failure_reason == "ConnectError"
    assert entry.last_ok_at is None
