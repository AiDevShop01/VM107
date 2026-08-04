"""Phase 85.1 — Partial upstream failure: executive_summary_writer cancellation.

Requirement mapping:
    PHASE85.1-REQ-4: Partial-upstream failure handled — executive_summary_writer
    is CANCELLED if either release_analyst or asset_exposure_analyst FAILED.
    publish_indicator_updated is NOT fired on partial-failure goals.

Design decision: executive_summary_writer depends on both upstream agents.
If either upstream reaches terminal FAILED state, there is no point running
the summary writer (its inputs are incomplete). Cancelling the downstream
task prevents a misleading summary from being published to WS consumers.

All tests are xfail until Plan 05 implements partial-failure handling.
"""

from __future__ import annotations

import pytest


def test_exec_summary_cancelled_when_release_analyst_failed(
    mock_goal_service,
    mock_dispatch_agent_sync,
    fixture_macro_release_task_docs,
    mock_brain_state_collection,
):
    """executive_summary_writer must be CANCELLED when release_analyst FAILED.

    Test setup:
        1. Force release_analyst to FAILED (simulating agent error after max_retries).
        2. asset_exposure_analyst completes normally.
        3. Dispatcher detects upstream failure.
        4. exec_summary_writer transitions to CANCELLED (not PENDING/RUNNING/COMPLETED).

    This prevents a partial summary from reaching WS consumers.
    """
    from workers.task_dispatcher import handle_upstream_failure  # noqa: F401

    store = mock_brain_state_collection._store
    release_task = fixture_macro_release_task_docs[0]
    asset_task = fixture_macro_release_task_docs[1]
    exec_task = fixture_macro_release_task_docs[2]

    # Set release_analyst to FAILED
    store[release_task["task_id"]]["status"] = "failed"
    store[release_task["task_id"]]["failure_reason"] = "max retries exhausted"

    # Set asset_exposure to COMPLETED (partial: one of two upstreams failed)
    store[asset_task["task_id"]]["status"] = "completed"

    goal_id = release_task["goal_id"]
    handle_upstream_failure(
        failed_task_id=release_task["task_id"],
        goal_id=goal_id,
        collection=mock_brain_state_collection,
        goal_service=mock_goal_service,
    )

    final_exec_doc = store.get(exec_task["task_id"], {})
    assert final_exec_doc.get("status") in ("cancelled", "CANCELLED"), (
        f"exec_summary_writer must be CANCELLED when release_analyst failed, "
        f"got {final_exec_doc.get('status')}"
    )


def test_publish_not_fired_when_exec_summary_cancelled(
    mock_goal_service,
    mock_orchestrator,
    fixture_macro_release_goal_doc,
    fixture_macro_release_task_docs,
    mock_brain_state_collection,
    monkeypatch,
):
    """publish_indicator_updated must NOT fire when exec_summary is CANCELLED.

    Goal completion hook must only trigger WS publish when ALL tasks reach
    COMPLETED.  A goal with any CANCELLED task is considered a partial failure
    and must not publish stale/incomplete data to WS consumers.
    """
    from unittest.mock import MagicMock, patch

    mock_publish = MagicMock()
    store = mock_brain_state_collection._store

    # Simulate: release_analyst FAILED → exec_summary CANCELLED
    release_task = fixture_macro_release_task_docs[0]
    exec_task = fixture_macro_release_task_docs[2]
    store[release_task["task_id"]]["status"] = "failed"
    store[exec_task["task_id"]]["status"] = "cancelled"

    with patch("publishers.macro_ws_invalidation.publish_indicator_updated", mock_publish):
        from workers.task_dispatcher import run_all_tasks_for_goal  # noqa: F401

        goal_id = fixture_macro_release_goal_doc["goal_id"]
        indicator_id = fixture_macro_release_goal_doc["payload"]["indicator_id"]

        run_all_tasks_for_goal(
            goal_id=goal_id,
            indicator_id=indicator_id,
            orchestrator=mock_orchestrator,
            goal_service=mock_goal_service,
        )

    assert mock_publish.call_count == 0, (
        "publish_indicator_updated must NOT fire when exec_summary is CANCELLED"
    )
