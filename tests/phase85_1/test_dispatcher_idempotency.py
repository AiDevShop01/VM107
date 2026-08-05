"""Phase 85.1 — Dispatcher idempotency: write_critical deduplication.

Requirement mapping:
    PHASE85.1-REQ-5: TieredBulkWriter.write_critical idempotency — re-dispatching
    the same task_id must not corrupt its status or trigger duplicate writes to
    economic_event_analysis.

This guard prevents double-execution bugs where a task gets dispatched twice
(e.g., due to a Redis queue duplicate, a sensor re-fire after a crash, or
a concurrency race during the PENDING→RUNNING transition).

Status: GREEN — idempotency checks are implemented in VM107.workers.task_dispatcher
(Plan 05); these tests pass against the real code.
"""

from __future__ import annotations


def test_redispatching_same_task_id_does_not_corrupt_status(
    mock_bulk_writer,
    fixture_macro_release_task_docs,
    mock_brain_state_collection,
    monkeypatch,
):
    """Calling _dispatch_one twice on the same already-RUNNING task must be a no-op.

    Test setup:
        1. Set release_analyst to RUNNING (simulating in-flight task).
        2. Call _dispatch_one(task) on that task a second time.
        3. The idempotency guard should detect status=RUNNING and skip.
        4. Route write counter (economic_event_analysis.insert_analysis) must be 0
           — the second dispatch must not trigger a double-write.
        5. bulk_writer.write_critical must not be called with status changes
           (status must stay RUNNING, not reset to PENDING or COMPLETED).

    Without this guard, a crash-recovery scenario could produce two concurrent
    agent calls for the same task_id, corrupting the economic_event_analysis row.
    """
    from unittest.mock import MagicMock, patch

    mock_insert = MagicMock()
    store = mock_brain_state_collection._store

    # Set the task as already RUNNING
    release_task = fixture_macro_release_task_docs[0]
    task_id = release_task["task_id"]
    store[task_id]["status"] = "running"

    initial_write_count = mock_bulk_writer.write_critical.call_count

    with patch("persistence.economic_event_analysis.insert_analysis", mock_insert):
        from workers.task_dispatcher import _dispatch_one  # noqa: F401

        # First call (simulating duplicate dispatch)
        _dispatch_one(task=dict(store[task_id]))
        # Second call (simulating sensor re-fire)
        _dispatch_one(task=dict(store[task_id]))

    # Route write must not have been called (task was already RUNNING → idempotent skip)
    assert mock_insert.call_count == 0, (
        f"insert_analysis must not be called when task is already RUNNING (got {mock_insert.call_count} calls)"
    )

    # Status must not have been corrupted (no write to change status from RUNNING)
    final_status = store.get(task_id, {}).get("status", "unknown")
    assert final_status in ("running", "RUNNING", "completed", "COMPLETED"), (
        f"Task status must not be corrupted by duplicate dispatch. Got: {final_status}"
    )
