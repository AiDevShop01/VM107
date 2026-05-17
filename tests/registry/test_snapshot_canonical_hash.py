"""Canonical snapshot serialization + content-addressed hash tests.

Verifies:
    test_formatting_invariant: YAML formatting differences don't affect hash
    test_contracts_change: contracts_request change does affect hash
    test_impact_change: impact_on_decision change does affect hash
    test_deprecated_change: deprecated flip affects hash
    test_tags_change: tags change affects hash
    test_list_order_invariant: list order within a field does NOT affect hash
    test_hash_length: snapshot_hash is exactly 64 hex chars
    test_hash_deterministic: building same snapshot 100 times produces identical hash
    test_versions_present_in_snapshot: snapshot metadata contains the 3 version constants
"""

from __future__ import annotations

import pytest
from freezegun import freeze_time

from fingpt_core.contracts.capability_registry import (
    CapabilitySnapshotEntry,
    CapabilityStatus,
    CapabilityType,
    ImpactLevel,
)

# These will be imported after snapshot.py is implemented
from core.registry.snapshot import (
    CANONICALIZER_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    VALIDATOR_VERSION,
    build_snapshot,
    compute_hash,
)


# ---------------------------------------------------------------------------
# Helpers to construct test entries
# ---------------------------------------------------------------------------


def _make_entry(**kwargs) -> CapabilitySnapshotEntry:
    """Create a CapabilitySnapshotEntry with sensible defaults."""
    defaults = dict(
        id="test_tool",
        type=CapabilityType.TOOL,
        status=CapabilityStatus.REAL,
        contracts_request=None,
        contracts_response=None,
        dependencies=(),
        related_capabilities=(),
        allowed_agent_profiles=("agent_zero",),
        impact_on_decision=ImpactLevel.MEDIUM,
        deprecated=False,
        tags=("test",),
        hard_scoped=False,
    )
    defaults.update(kwargs)
    return CapabilitySnapshotEntry(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_formatting_invariant():
    """Two entries semantically identical but conceptually 'formatted differently'
    (different field insertion order simulated via separate construction paths)
    must produce identical hashes.

    Since CapabilitySnapshotEntry is a frozen Pydantic model, 'formatting'
    differences only arise at the YAML layer (before parsing). Once parsed to
    the same field values, the hash must be identical.
    """
    entry_a = _make_entry(id="my_tool", tags=("alpha", "beta"))
    entry_b = _make_entry(id="my_tool", tags=("alpha", "beta"))

    assert compute_hash([entry_a]) == compute_hash([entry_b])


def test_contracts_change():
    """Changing contracts_request while keeping (id, status) the same must
    produce a DIFFERENT hash."""
    entry_a = _make_entry(id="my_tool", contracts_request=None)
    entry_b = _make_entry(
        id="my_tool",
        contracts_request="fingpt_core.contracts.analytics.snapshot.TradeQualityScoreResult",
    )

    assert compute_hash([entry_a]) != compute_hash([entry_b])


def test_impact_change():
    """Changing impact_on_decision from HIGH to MEDIUM must produce a DIFFERENT hash."""
    entry_a = _make_entry(id="my_tool", impact_on_decision=ImpactLevel.HIGH)
    entry_b = _make_entry(id="my_tool", impact_on_decision=ImpactLevel.MEDIUM)

    assert compute_hash([entry_a]) != compute_hash([entry_b])


def test_deprecated_change():
    """Flipping deprecated from False to True must produce a DIFFERENT hash."""
    entry_a = _make_entry(id="my_tool", deprecated=False)
    entry_b = _make_entry(id="my_tool", deprecated=True)

    assert compute_hash([entry_a]) != compute_hash([entry_b])


def test_tags_change():
    """Changing tags must produce a DIFFERENT hash."""
    entry_a = _make_entry(id="my_tool", tags=("alpha",))
    entry_b = _make_entry(id="my_tool", tags=("beta",))

    assert compute_hash([entry_a]) != compute_hash([entry_b])


def test_list_order_invariant():
    """dependencies=[a, b] vs dependencies=[b, a] (same set, different order)
    must produce IDENTICAL hashes because canonical serialization sorts lists."""
    entry_a = _make_entry(id="my_tool", dependencies=("dep_a", "dep_b"))
    entry_b = _make_entry(id="my_tool", dependencies=("dep_b", "dep_a"))

    assert compute_hash([entry_a]) == compute_hash([entry_b])


def test_hash_length():
    """snapshot_hash must be exactly 64 hex characters (SHA-256 output)."""
    entry = _make_entry(id="my_tool")
    h = compute_hash([entry])
    assert len(h) == 64, f"Expected 64 chars, got {len(h)}: {h!r}"
    assert all(c in "0123456789abcdef" for c in h), f"Not valid hex: {h!r}"


def test_hash_deterministic():
    """Building the same snapshot 100 times produces identical hashes."""
    entry = _make_entry(id="my_tool", tags=("x", "y"), dependencies=("d1",))
    hashes = {compute_hash([entry]) for _ in range(100)}
    assert len(hashes) == 1, f"Expected 1 unique hash across 100 runs, got {len(hashes)}"


@freeze_time("2026-05-17T00:00:00Z")
def test_versions_present_in_snapshot():
    """Snapshot metadata must include validator_version, canonicalizer_version,
    and snapshot_schema_version matching the module-level constants."""
    entry = _make_entry(id="my_tool")
    snapshot = build_snapshot([entry])

    assert snapshot.validator_version == VALIDATOR_VERSION, (
        f"Expected validator_version={VALIDATOR_VERSION!r}, "
        f"got {snapshot.validator_version!r}"
    )
    assert snapshot.canonicalizer_version == CANONICALIZER_VERSION, (
        f"Expected canonicalizer_version={CANONICALIZER_VERSION!r}, "
        f"got {snapshot.canonicalizer_version!r}"
    )
    assert snapshot.snapshot_schema_version == SNAPSHOT_SCHEMA_VERSION, (
        f"Expected snapshot_schema_version={SNAPSHOT_SCHEMA_VERSION!r}, "
        f"got {snapshot.snapshot_schema_version!r}"
    )
    # Sanity: entries are frozen tuple
    assert isinstance(snapshot.entries, tuple)
    # Sanity: hash is 64 chars
    assert len(snapshot.snapshot_hash) == 64
