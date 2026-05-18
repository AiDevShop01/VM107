"""Phase 48 / Phase 56 — VM107-side event emission package.

Public surface:
    emit_event(event_type, category, correlation_id, payload, *, causality_scope="IDEA") -> None
    Phase56EmitError
    validate_snapshot_for_replay(stored_hash) -> None
    SnapshotMismatchError

Env-driven config (no fallback per memory/feedback_env_driven_no_fallbacks.md):
    VM100_INTERNAL_BASE_URL — required; read via os.environ["VM100_INTERNAL_BASE_URL"]
"""
from core.events.phase56_client import (
    Phase56EmitError,
    SnapshotMismatchError,
    emit_event,
    validate_snapshot_for_replay,
)

__all__ = [
    "Phase56EmitError",
    "SnapshotMismatchError",
    "emit_event",
    "validate_snapshot_for_replay",
]
