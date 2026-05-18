"""VM107-side Phase 56 emit client + replay snapshot validation primitive.

REGISTER_CAPABILITY: type=service, id=phase56_emit_client_vm107, path=VM107/core/events/phase56_client.py

This is the VM107-side client that POSTs refinement-lifecycle events to
VM100's Phase 56 event store. It mirrors the structural pattern from
``Dagster/fingpt_orchestration/src/fingpt_orchestration/clients/phase56_event_store_client.py``
but strips Dagster-specific bits (no Dagster context, no Dagster logger).

Env-driven config (Directive #4, memory/feedback_env_driven_no_fallbacks.md):
    VM100_INTERNAL_BASE_URL — required at every emit call.
    The env var is read via the direct subscript form only — no fallback API,
    no default value. Missing env raises KeyError at the call site.
    Fail-fast beats silent misconfiguration.

Retry policy (Plan 48-03 Task 3.1 contract):
    - HTTP 2xx → return None
    - HTTP 4xx → raise Phase56EmitError IMMEDIATELY (no retry — client error)
    - HTTP 5xx → retry exactly ONCE, then raise Phase56EmitError
    - httpx.ConnectError → retry exactly ONCE, then raise Phase56EmitError

The orchestrator (Plan 48-04+) catches Phase56EmitError and treats it as a
terminal pipeline-stage degradation (BUILD_FAILURE termination) per
CONTEXT § Decision 18.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from core.registry.capability_registry import CapabilityRegistry

log = logging.getLogger("vm107.core.events.phase56_client")

_EMIT_PATH = "/api/journal/internal/events/emit"
_DEFAULT_TIMEOUT_SECONDS = 5.0


class Phase56EmitError(RuntimeError):
    """Raised when emit_event cannot persist an event to the Phase 56 store.

    Carries the failed status code (if any) and the body of the failing response
    so the orchestrator can map to a precise TerminationReason.BUILD_FAILURE
    sub-state.
    """

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SnapshotMismatchError(RuntimeError):
    """Raised when a replay query's stored registry hash differs from current.

    Per CONTEXT § Decision 15: replay APIs MUST require ``registry_snapshot_hash``.
    Mismatch on replay = HARD FAIL, no "best effort replay."
    """

    def __init__(self, stored_hash: str, current_hash: str) -> None:
        super().__init__(
            f"Snapshot mismatch on replay — stored={stored_hash!r} current={current_hash!r}. "
            "Phase 48 loops are anchored to a frozen capability surface; replay against a "
            "different snapshot would yield non-deterministic results."
        )
        self.stored_hash = stored_hash
        self.current_hash = current_hash


def _utc_iso8601_now() -> str:
    """UTC timestamp as ISO 8601 with 'Z' suffix (Phase 56 convention)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def emit_event(
    event_type: str,
    category: str,
    correlation_id: str,
    payload: dict[str, Any],
    *,
    causality_scope: str = "IDEA",
) -> None:
    """POST one refinement-lifecycle event to the Phase 56 event store.

    Args:
        event_type: Canonical event name (e.g., ``refinement_loop_started``).
            Registered as ``VM107/registry/event_type/<name>.yaml`` (Plan 48-07).
        category: Phase 56 event category — e.g., ``"cognition"``, ``"lifecycle"``.
        correlation_id: Per-loop correlation id (Phase 56 lock).
        payload: Event-specific payload dict (orchestrator builds this).
        causality_scope: Phase 56 causality scope. Default ``"IDEA"`` per
            planner decision for V1 (CONTEXT § Decision 18).

    Raises:
        KeyError: when ``VM100_INTERNAL_BASE_URL`` env var is not set.
        Phase56EmitError: on 4xx (no retry), 5xx (after one retry), or
            ``httpx.ConnectError`` (after one retry).
    """
    base_url = os.environ["VM100_INTERNAL_BASE_URL"]
    url = base_url.rstrip("/") + _EMIT_PATH

    body: dict[str, Any] = {
        "event_type": event_type,
        "category": category,
        "correlation_id": correlation_id,
        "causality_scope": causality_scope,
        "occurred_at": _utc_iso8601_now(),
        "payload": payload,
    }

    # Retry policy: 4xx → no retry, 5xx / ConnectError → retry exactly once.
    last_status: int | None = None
    last_body: str = ""

    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
                response = client.post(url, json=body, headers={})
        except httpx.ConnectError as exc:
            log.warning(
                "phase56_client: ConnectError on attempt %d for event_type=%s: %s",
                attempt, event_type, exc,
            )
            if attempt == 2:
                raise Phase56EmitError(
                    f"ConnectError after retry: {exc}",
                    status_code=None,
                    body=str(exc),
                ) from exc
            continue

        status = response.status_code
        if 200 <= status < 300:
            return None

        last_status = status
        # Best-effort body capture for the error message.
        try:
            last_body = response.text
        except Exception:
            last_body = ""

        if 400 <= status < 500:
            # Client error — do NOT retry.
            raise Phase56EmitError(
                f"HTTP {status} from Phase 56 emit endpoint (no retry on 4xx): {last_body}",
                status_code=status,
                body=last_body,
            )

        if 500 <= status < 600:
            log.warning(
                "phase56_client: HTTP %d on attempt %d for event_type=%s",
                status, attempt, event_type,
            )
            if attempt == 2:
                raise Phase56EmitError(
                    f"HTTP {status} from Phase 56 emit endpoint after retry: {last_body}",
                    status_code=status,
                    body=last_body,
                )
            continue

        # Other status (1xx / 3xx) — treat as failure.
        raise Phase56EmitError(
            f"Unexpected HTTP {status} from Phase 56 emit endpoint: {last_body}",
            status_code=status,
            body=last_body,
        )

    # Defensive: should not be reached.
    raise Phase56EmitError(
        f"emit_event exhausted retries (last_status={last_status})",
        status_code=last_status,
        body=last_body,
    )


def validate_snapshot_for_replay(stored_hash: str) -> None:
    """Replay-time guard: raise SnapshotMismatchError if current != stored.

    Called by ReplayQueryService.get_refinement_timeline (Plan 48-09 wires it).
    Per CONTEXT § Decision 15: replay is HARD FAIL on snapshot drift.

    Args:
        stored_hash: The ``loop_registry_snapshot_hash`` recorded on the loop.

    Raises:
        SnapshotMismatchError: when the live registry snapshot differs.
    """
    current = CapabilityRegistry.get().snapshot_hash
    if current != stored_hash:
        raise SnapshotMismatchError(stored_hash=stored_hash, current_hash=current)
    return None
