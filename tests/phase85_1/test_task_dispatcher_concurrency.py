"""Phase 85.1 — Concurrency cap tests.

Requirement mapping:
    PHASE85.1-REQ-4: MAX_CONCURRENT cap honoured — with 10 PENDING tasks and
    VM107_TASK_DISPATCHER_MAX_CONCURRENT=2, at most 2 tasks are RUNNING at any
    given point during dispatch.

All tests are xfail until Plan 05 implements concurrency gating in
VM107.workers.task_dispatcher.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="Plan 05 — concurrency cap not yet implemented", strict=False)
def test_dispatcher_honours_max_concurrent_cap(
    monkeypatch,
    mock_dispatch_agent_sync,
    mock_brain_state_collection,
):
    """With MAX_CONCURRENT=2 and 10 PENDING tasks, running count never exceeds 2.

    Test setup:
        1. Set VM107_TASK_DISPATCHER_MAX_CONCURRENT=2 via monkeypatch.
        2. Populate store with 10 PENDING tasks (no blocked_by).
        3. Patch _dispatch_agent_sync to sleep 200ms before returning.
        4. Run dispatcher concurrently.
        5. Poll collection._store at 50ms intervals — max RUNNING count must be ≤ 2.

    The dispatch loop is expected to use asyncio or threading with a semaphore.
    This test uses time.sleep mocking to control the in-flight window.
    """
    import os
    import time
    import uuid
    from unittest.mock import MagicMock

    from tests.phase85_1.fixtures.brain_state_documents import make_task_doc

    # Build 10 PENDING tasks in the store
    goal_id = f"goal_{uuid.uuid4().hex[:8]}"
    task_ids = []
    for _ in range(10):
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task_ids.append(task_id)
        mock_brain_state_collection._store[task_id] = make_task_doc(
            task_id=task_id,
            goal_id=goal_id,
            agent_name="vm107.macro_release_analyst",
            blocked_by=[],
            status="pending",
        )

    monkeypatch.setenv("VM107_TASK_DISPATCHER_MAX_CONCURRENT", "2")

    # Track maximum concurrent RUNNING count
    max_running_seen = [0]

    original_side_effect = mock_dispatch_agent_sync.side_effect

    def _slow_dispatch(*args, **kwargs):
        # Count current RUNNING tasks
        running_count = sum(
            1 for doc in mock_brain_state_collection._store.values()
            if doc.get("status") == "running"
        )
        max_running_seen[0] = max(max_running_seen[0], running_count)
        time.sleep(0.01)  # Simulated agent latency
        return ('{"result": "ok"}', {"tokens_used": 50, "latency_ms": 10})

    mock_dispatch_agent_sync.side_effect = _slow_dispatch

    from workers.task_dispatcher import dispatch_batch  # noqa: F401

    dispatch_batch(
        collection=mock_brain_state_collection,
        max_concurrent=2,
    )

    assert max_running_seen[0] <= 2, (
        f"Concurrency cap violated: max RUNNING observed = {max_running_seen[0]} (cap=2)"
    )
