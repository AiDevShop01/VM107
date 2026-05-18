"""Phase 48 snapshot-freeze primitive — idempotent capture at iteration 0.

Implements REQ-48-D15. CONTEXT § Decision 15: a refinement loop = one coherent
cognition universe. The capability surface is frozen at loop start; mid-loop
registry mutations are IGNORED.

``freeze_snapshot_hash(db, loop_id) -> str``:
  - If ``refinement_loops[loop_id].loop_registry_snapshot_hash`` is already set,
    return that value (idempotent — no re-fetch).
  - Otherwise, read ``CapabilityRegistry.get().snapshot_hash`` (PROPERTY access
    per Wave 0 finding 3) and persist it to the doc.

NOTE on naming: CONTEXT § Decision 15 referenced a method-form name that does
NOT exist on CapabilityRegistry. The real API is the ``snapshot_hash``
@property defined at ``VM107/core/registry/capability_registry.py:179``.
This module uses the property form: ``CapabilityRegistry.get().snapshot_hash``.
"""
from __future__ import annotations

from typing import Any

from core.registry.capability_registry import CapabilityRegistry

_REFINEMENT_LOOPS = "refinement_loops"


def freeze_snapshot_hash(db: Any, loop_id: str) -> str:
    """Capture the registry snapshot hash ONCE per loop. Idempotent.

    Args:
        db: pymongo Database (or mongomock).
        loop_id: The loop being initialized / queried.

    Returns:
        The frozen hash string. Always equal to the value of
        ``CapabilityRegistry.get().snapshot_hash`` at the moment the loop was
        first initialized — even if the registry has mutated since.
    """
    doc = db[_REFINEMENT_LOOPS].find_one(
        {"_id": loop_id}, {"loop_registry_snapshot_hash": 1}
    )
    if doc and doc.get("loop_registry_snapshot_hash"):
        return doc["loop_registry_snapshot_hash"]

    # First freeze for this loop — read the live property and persist.
    fresh_hash = CapabilityRegistry.get().snapshot_hash
    db[_REFINEMENT_LOOPS].update_one(
        {"_id": loop_id},
        {"$set": {"loop_registry_snapshot_hash": fresh_hash}},
    )
    return fresh_hash
