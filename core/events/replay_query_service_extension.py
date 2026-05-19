"""Phase 48 Plan 48-09 — VM107-side ReplayQueryService extension.

REGISTER_CAPABILITY: type=service, id=replay_query_service_extension_vm107, path=VM107/core/events/replay_query_service_extension.py

Reads refinement-loop event timelines back from Phase 56's event store with
HARD FAIL snapshot validation per CONTEXT § Decision 15.

CONTEXT § Decision 18: Phase 56 ReplayQueryService is the canonical reader;
this VM107-side extension wraps the cross-VM read in:
    1. ``get_refinement_timeline(loop_id)``:
       a. Look up RefinementLoopState by loop_id to find stored snapshot_hash.
       b. ``validate_snapshot_for_replay(stored_hash)`` — HARD FAIL on mismatch.
       c. Read events filtered by ``correlation_id=loop_id``, ordered by
          ``occurred_at`` (per Phase 56's 3 per-entity sequence ordering).
       d. Return the timeline.

CONTEXT § Decision 15 (HARD FAIL contract):
    "Replay APIs MUST require ``registry_snapshot_hash``. Mismatch on replay =
     HARD FAIL, no 'best effort replay.'"
    The wrapper raises ``SnapshotMismatchError`` from ``phase56_client.py``;
    callers MUST handle or propagate. No log-and-continue, no degraded-replay.

Plan 09 deviation Rule 3 — Blocking (cross-VM read substrate):
    The canonical Phase 56 ReplayQueryService lives in VM100's Django backend.
    A Phase 56 cross-VM read API was not in scope for Plan 09 — until VM100
    ships an HTTP endpoint that exposes ``get_events_by_correlation_id``,
    this VM107 extension reads from a local ``events`` Mongo collection
    (used as the test substrate). The public surface — ``get_refinement_timeline``
    + snapshot HARD FAIL — is the canonical contract; the underlying read
    substrate is swappable to the future VM100 API without changing callers.

Env-driven config (Directive #4): no soft-get accessors anywhere in this
module. Mongo handle comes from helpers/mongo.py (which uses os.environ
direct subscript at its own boundary).
"""
from __future__ import annotations

import logging
from typing import Any

from core.events.phase56_client import (
    SnapshotMismatchError,
    validate_snapshot_for_replay,
)
from core.registry.capability_registry import CapabilityRegistry

log = logging.getLogger("vm107.core.events.replay_query_service_extension")

_REFINEMENT_LOOPS = "refinement_loops"
_EVENTS = "events"


def _get_db() -> Any:
    """Resolve MongoDB handle. Tests monkeypatch this directly."""
    from helpers.mongo import get_mongo_db
    return get_mongo_db()


def get_refinement_timeline(*, loop_id: str) -> list[dict[str, Any]]:
    """Read back the full event timeline for a refinement loop.

    CONTEXT § Decision 15 HARD FAIL: validates the stored
    ``loop_registry_snapshot_hash`` against the live CapabilityRegistry
    BEFORE reading any events. Mismatch raises ``SnapshotMismatchError``.

    Args:
        loop_id: The refinement loop's correlation_id (== loop_id == _id).

    Returns:
        List of event dicts ordered by ``occurred_at`` ASC. Each dict has
        the canonical Phase 56 shape: ``{event_type, correlation_id,
        occurred_at, payload, ...}``.

    Raises:
        SnapshotMismatchError: when the stored snapshot hash differs from
            the live CapabilityRegistry snapshot. HARD FAIL — no best-effort
            replay against a mutated capability surface.
        LookupError: when ``loop_id`` is not present in ``refinement_loops``.
    """
    db = _get_db()

    # 1. Look up the loop's stored snapshot hash.
    loop_doc = db[_REFINEMENT_LOOPS].find_one({"_id": loop_id})
    if loop_doc is None:
        # Try by loop_id field for tests / migration robustness.
        loop_doc = db[_REFINEMENT_LOOPS].find_one({"loop_id": loop_id})
    if loop_doc is None:
        raise LookupError(
            f"refinement_loops doc not found for loop_id={loop_id!r}; "
            "cannot validate replay snapshot."
        )

    stored_hash = loop_doc.get("loop_registry_snapshot_hash")
    if not stored_hash:
        raise LookupError(
            f"refinement_loops doc for loop_id={loop_id!r} missing "
            "loop_registry_snapshot_hash — cannot validate replay."
        )

    # 2. HARD FAIL on snapshot mismatch (Decision 15).
    validate_snapshot_for_replay(stored_hash)

    # 3. Read events filtered by correlation_id, ordered by occurred_at.
    cursor = db[_EVENTS].find({"correlation_id": loop_id}).sort("occurred_at", 1)
    events = list(cursor)

    # Strip Mongo-internal _id for clean caller-facing dicts.
    for ev in events:
        ev.pop("_id", None)

    log.info(
        "get_refinement_timeline(loop_id=%s) returned %d events (snapshot=%s)",
        loop_id, len(events), stored_hash,
    )
    return events


__all__ = [
    "get_refinement_timeline",
    "SnapshotMismatchError",
    "CapabilityRegistry",
]
