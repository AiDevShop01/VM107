"""Phase 85.1 — WS chain end-to-end: all tasks complete → publish_indicator_updated.

Requirement mapping:
    PHASE85.1-REQ-1 (WS chain): All-3-tasks-COMPLETED →
        publish_indicator_updated(indicator_id) fires exactly ONCE.

Both tests are xfail until Plan 02 implements:
    - VM107.workers.task_dispatcher (runs all 3 tasks in sequence via the goal)
    - VM107.publishers.macro_ws_invalidation.publish_indicator_updated (already exists)
    - Deduplication guard (W5 contract): in-loop dedup MUST suppress duplicate calls.

W5 dedup contract:
    The listener's lambda hook AND the dispatcher's defence-in-depth call site
    both route through the same mock symbol.  The in-loop dedup guard must
    suppress the second invocation so call_count == 1, not >= 1.

    If this test is written to assert >= 1, it misses double-publish bugs that
    would spam the WS room with stale data.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="Plan 02 — WS chain dispatcher not yet implemented", strict=False)
def test_three_tasks_completed_fires_publish_indicator_updated_once(
    monkeypatch,
    mock_goal_service,
    mock_orchestrator,
    fixture_macro_release_goal_doc,
    fixture_macro_release_task_docs,
):
    """All 3 tasks reaching COMPLETED fires publish_indicator_updated exactly once.

    Test flow:
        1. Pre-populate store with goal + 3 tasks (already done by fixtures).
        2. Simulate dispatcher completing each task in order:
               release_analyst → on_task_completed(release_id)
               asset_exposure  → on_task_completed(asset_id)
               [exec_summary unblocked: blocked_by becomes []]
               exec_summary    → on_task_completed(exec_id)
        3. On goal terminal (all tasks COMPLETED), orchestrator.notify_goal_completed
           should invoke the registered WS publish hook.
        4. publish_indicator_updated must be called EXACTLY once.

    The patch covers BOTH the listener-path lambda AND the dispatcher defence-in-depth
    call site so the dedup guard is exercised.
    """
    from unittest.mock import MagicMock, patch

    mock_publish = MagicMock()

    with patch("VM107.publishers.macro_ws_invalidation.publish_indicator_updated", mock_publish):
        from VM107.workers.task_dispatcher import run_all_tasks_for_goal  # noqa: F401

        goal_id = fixture_macro_release_goal_doc["goal_id"]
        indicator_id = fixture_macro_release_goal_doc["payload"]["indicator_id"]

        run_all_tasks_for_goal(
            goal_id=goal_id,
            indicator_id=indicator_id,
            orchestrator=mock_orchestrator,
            goal_service=mock_goal_service,
        )

    # EXACTLY once — not >= 1 (W5 dedup contract)
    assert mock_publish.call_count == 1, (
        f"publish_indicator_updated must be called exactly once (W5 dedup contract), "
        f"got {mock_publish.call_count}"
    )
    # Called with the correct indicator_id
    call_args = mock_publish.call_args
    assert indicator_id in str(call_args), (
        f"publish_indicator_updated must be called with indicator_id={indicator_id!r}"
    )


@pytest.mark.xfail(reason="Plan 02 — WS chain dispatcher not yet implemented", strict=False)
def test_publish_not_fired_when_any_task_failed(
    monkeypatch,
    mock_goal_service,
    mock_orchestrator,
    fixture_macro_release_goal_doc,
    fixture_macro_release_task_docs,
    mock_brain_state_collection,
):
    """If any task transitions to FAILED, publish_indicator_updated must NOT fire.

    Test flow:
        1. Set release_analyst to FAILED (simulating agent error).
        2. Run dispatcher.
        3. Goal should transition to FAILED (not COMPLETED).
        4. publish_indicator_updated must not be called.
    """
    from unittest.mock import MagicMock, patch

    mock_publish = MagicMock()

    # Force release_analyst to FAILED in store
    store = mock_brain_state_collection._store
    release_task = fixture_macro_release_task_docs[0]
    store[release_task["task_id"]]["status"] = "failed"

    with patch("VM107.publishers.macro_ws_invalidation.publish_indicator_updated", mock_publish):
        from VM107.workers.task_dispatcher import run_all_tasks_for_goal  # noqa: F401

        goal_id = fixture_macro_release_goal_doc["goal_id"]
        indicator_id = fixture_macro_release_goal_doc["payload"]["indicator_id"]

        run_all_tasks_for_goal(
            goal_id=goal_id,
            indicator_id=indicator_id,
            orchestrator=mock_orchestrator,
            goal_service=mock_goal_service,
        )

    assert mock_publish.call_count == 0, (
        "publish_indicator_updated must NOT be called when any task has FAILED"
    )
