"""Phase 85.1 — Retry semantics tests.

Requirement mapping:
    PHASE85.1-REQ-4: Failed task retried up to max_retries then transitions FAILED.
    Retry must increment retry_count and write failure_reason on final failure.

All tests are xfail until Plan 05 implements retry logic in
VM107.workers.task_dispatcher.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="Plan 05 — retry semantics not yet implemented", strict=False)
def test_failed_task_retries_up_to_max_retries(
    mock_dispatch_agent_sync,
    fixture_macro_release_task_docs,
    mock_goal_service,
    mock_brain_state_collection,
):
    """A task that fails 3 times exhausts max_retries and reaches FAILED state.

    Expected state machine:
        PENDING → RUNNING (attempt 1) → PENDING (retry 1, retry_count=1)
        PENDING → RUNNING (attempt 2) → PENDING (retry 2, retry_count=2)
        PENDING → RUNNING (attempt 3) → PENDING (retry 3, retry_count=3)
        PENDING → RUNNING (attempt 4, retry_count >= max_retries=3) → FAILED

    Each failure increments retry_count via bulk_writer.write_critical.
    On final failure, status transitions to FAILED (not PENDING).
    """
    from VM107.workers.task_dispatcher import run_task_with_retry  # noqa: F401

    release_task = dict(fixture_macro_release_task_docs[0])
    release_task["max_retries"] = 3
    release_task["retry_count"] = 0

    # Force 3 failures then success
    call_count = [0]

    def _failing_dispatch(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 3:
            raise RuntimeError("Agent Zero returned an error")
        return ('{"result": "ok"}', {"tokens_used": 50})

    mock_dispatch_agent_sync.side_effect = _failing_dispatch

    run_task_with_retry(task=release_task, goal_service=mock_goal_service)

    # After 3 failures exceeding max_retries=3, final status must be FAILED
    # (The 4th attempt would be attempt 4, which is > max_retries=3)
    store = mock_brain_state_collection._store
    final_doc = store.get(release_task["task_id"], {})
    assert final_doc.get("status") in ("failed", "FAILED"), (
        f"Task must be FAILED after exhausting max_retries, got {final_doc.get('status')}"
    )


@pytest.mark.xfail(reason="Plan 05 — retry semantics not yet implemented", strict=False)
def test_failed_task_writes_failure_reason(
    mock_dispatch_agent_sync,
    fixture_macro_release_task_docs,
    mock_goal_service,
    mock_brain_state_collection,
):
    """On terminal FAILED state, dispatcher writes failure_reason to the task document.

    The failure_reason must capture the exception message so operators can
    diagnose why a task failed without digging into logs.
    """
    from VM107.workers.task_dispatcher import run_task_with_retry  # noqa: F401

    release_task = dict(fixture_macro_release_task_docs[0])
    release_task["max_retries"] = 0  # Fail immediately on first error

    error_msg = "Agent Zero: model refused request — content policy"
    mock_dispatch_agent_sync.side_effect = RuntimeError(error_msg)

    run_task_with_retry(task=release_task, goal_service=mock_goal_service)

    store = mock_brain_state_collection._store
    final_doc = store.get(release_task["task_id"], {})
    failure_reason = final_doc.get("failure_reason", "")
    assert failure_reason, "failure_reason must be non-empty after terminal FAILED"
    assert error_msg in str(failure_reason), (
        f"failure_reason must include the exception message. "
        f"Got: {failure_reason!r}"
    )
