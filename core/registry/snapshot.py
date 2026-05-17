"""Canonical snapshot serialization + content-addressed SHA-256 hashing.

The hash is computed over the SEMANTIC fields of the registry (LD-3 fields),
not over raw YAML bytes. This guarantees:

    - Formatting invariance: YAML comments, key ordering, whitespace do NOT
      change the hash. Only actual semantic values matter.
    - Semantic sensitivity: changing contracts, impact_on_decision, deprecated,
      tags, or any other LD-3 field DOES change the hash.
    - List-order invariance: dependencies=[a,b] and dependencies=[b,a] hash
      identically because canonical serialization sorts all list fields.

Canonical serialization algorithm (RESEARCH §Pattern 3):
    1. Sort entries by (type.value, id) for deterministic ordering.
    2. For each entry, project to a canonical dict with sorted list fields.
    3. Serialize to JSON with sort_keys=True and no whitespace (separators=(',',':')).
    4. Compute SHA-256 of the UTF-8 bytes.

Version constants (LD-2 — surfaced for replay consistency):
    VALIDATOR_VERSION: Version of the 7-stage validation pipeline.
    CANONICALIZER_VERSION: Version of this canonical serialization algorithm.
    SNAPSHOT_SCHEMA_VERSION: Version of the canonical payload shape itself.
        Changing the snapshot schema IS an intentional cognition-truth change.
        The runtime versions (validator/canonicalizer) are recorded alongside
        the hash for traceability but are NOT included in the hash payload —
        changing only the tool version without changing the semantic content
        must not invalidate the hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fingpt_core.contracts.capability_registry import (
    CapabilityRegistrySnapshot,
    CapabilitySnapshotEntry,
)

CANONICALIZER_VERSION = "1.0"
VALIDATOR_VERSION = "1.0"
SNAPSHOT_SCHEMA_VERSION = "1.0"


def _entry_to_canonical_dict(e: CapabilitySnapshotEntry) -> dict:
    """Project a CapabilitySnapshotEntry to a canonical dict for hashing.

    All list-valued fields are sorted to guarantee list-order invariance.
    Enum values are serialized as their string value for JSON stability.
    """
    return {
        "id": e.id,
        "type": e.type.value,
        "status": e.status.value,
        "contracts_request": e.contracts_request,
        "contracts_response": e.contracts_response,
        "dependencies": sorted(e.dependencies),
        "related_capabilities": sorted(e.related_capabilities),
        "allowed_agent_profiles": sorted(e.allowed_agent_profiles),
        "impact_on_decision": e.impact_on_decision.value,
        "deprecated": e.deprecated,
        "tags": sorted(e.tags),
        "hard_scoped": e.hard_scoped,
    }


def _canonical_payload(entries: list[CapabilitySnapshotEntry]) -> bytes:
    """Build the canonical JSON payload for hashing.

    CRITICAL: The payload MUST NOT include snapshot_generated_at,
    validation_passed_at, validator_version, or canonicalizer_version —
    those are traceability metadata. Including them would cause two
    semantically-identical registries to hash differently if built at
    different times or by different tool versions.

    snapshot_schema_version IS included: changing the schema shape IS an
    intentional cognition-truth change that warrants a different hash.
    """
    sorted_entries = sorted(entries, key=lambda e: (e.type.value, e.id))
    payload = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "entries": [_entry_to_canonical_dict(e) for e in sorted_entries],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_hash(entries: list[CapabilitySnapshotEntry]) -> str:
    """Compute SHA-256 hash of the canonical registry payload.

    Returns a 64-character lowercase hex string.
    Deterministic: identical entries always produce identical hash.
    Semantic: only content changes (not timestamps/tool versions) change the hash.
    """
    return hashlib.sha256(_canonical_payload(entries)).hexdigest()


def build_snapshot(entries: list[CapabilitySnapshotEntry]) -> CapabilityRegistrySnapshot:
    """Build a frozen CapabilityRegistrySnapshot from a list of entries.

    Entries are sorted by (type, id) in the snapshot.
    The snapshot_hash is the canonical SHA-256 over the semantic payload.
    """
    now = datetime.now(timezone.utc)
    sorted_entries = tuple(sorted(entries, key=lambda e: (e.type.value, e.id)))
    return CapabilityRegistrySnapshot(
        entries=sorted_entries,
        snapshot_hash=compute_hash(entries),
        snapshot_generated_at=now,
        validation_passed_at=now,
        validator_version=VALIDATOR_VERSION,
        canonicalizer_version=CANONICALIZER_VERSION,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
    )
