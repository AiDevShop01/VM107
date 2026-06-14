"""Phase 85.1 — Task Dispatcher: happy path, routing, and Pitfall 2 ordering.

Requirement mapping:
    PHASE85.1-REQ-1: Dispatcher dequeues PENDING task, invokes Agent Zero,
                     transitions COMPLETED, calls on_task_completed, fires
                     notify_goal_completed on goal terminal.

All tests are marked xfail(strict=False) — Plan 02 flips them GREEN by
implementing VM107.workers.task_dispatcher and the parse_and_persist routing
layer.  Test names are FIXED — do not rename; Plan 02 verify-block references
them verbatim.

Pitfall 2 guard (test_dispatch_agent_sync_sets_profile_id_before_monologue):
    Slot-30 router (fail-fast) + slot-20 B1 write both filter on profile_id,
    not config.profile.  profile_id must be set via sub.set_data("profile_id")
    BEFORE sub.hist_add_user_message() BEFORE asyncio.run(sub.monologue()).
    Without this ordering, the router drops the message silently.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Happy-path status-transition tests
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Plan 02 — task dispatcher not yet implemented", strict=False)
def test_dispatcher_picks_pending_task_and_marks_running(
    mock_brain_state_collection,
    mock_bulk_writer,
    mock_dispatch_agent_sync,
    fixture_macro_release_task_docs,
):
    """Dispatcher dequeues the first PENDING task and sets status=RUNNING.

    Expected behaviour:
        1. Scan collection for tasks with status=pending and blocked_by=[].
        2. Pick the first eligible task.
        3. Call bulk_writer.write_critical(task_id, {"status": "running"}).
        4. Invoke _dispatch_agent_sync with the task's agent_name.
    """
    from VM107.workers.task_dispatcher import dispatch_next_task  # noqa: F401

    release_task = fixture_macro_release_task_docs[0]
    assert release_task["status"] == "pending"

    dispatch_next_task(
        collection=mock_brain_state_collection,
        bulk_writer=mock_bulk_writer,
    )

    # Assert RUNNING write happened
    mock_bulk_writer.write_critical.assert_called()
    call_kwargs = {
        k: v
        for call in mock_bulk_writer.write_critical.call_args_list
        for k, v in (call.args[1] if call.args else {}).items()
    }
    assert call_kwargs.get("status") == "running"


@pytest.mark.xfail(reason="Plan 02 — task dispatcher not yet implemented", strict=False)
def test_dispatcher_transitions_completed_on_success(
    mock_goal_service,
    mock_dispatch_agent_sync,
    fixture_macro_release_task_docs,
):
    """After _dispatch_agent_sync returns without error, task transitions to COMPLETED.

    Expected behaviour:
        1. Task begins as RUNNING.
        2. _dispatch_agent_sync returns (output_str, telemetry).
        3. parse_and_persist called with output + goal_payload.
        4. bulk_writer.write_critical(task_id, {"status": "completed"}).
    """
    from VM107.workers.task_dispatcher import run_task  # noqa: F401

    release_task = fixture_macro_release_task_docs[0]
    run_task(task=release_task, goal_service=mock_goal_service)

    # Verify terminal state written
    completed_writes = [
        call for call in mock_goal_service.bulk_writer.write_critical.call_args_list
        if call.args and isinstance(call.args[1], dict) and call.args[1].get("status") == "completed"
    ]
    assert len(completed_writes) >= 1


@pytest.mark.xfail(reason="Plan 02 — task dispatcher not yet implemented", strict=False)
def test_dispatcher_calls_on_task_completed_after_terminal(
    mock_goal_service,
    fixture_macro_release_task_docs,
):
    """After task reaches COMPLETED, dispatcher calls goal_service.on_task_completed.

    Expected behaviour:
        on_task_completed(task_id) is invoked exactly once per completed task,
        allowing the DAG unblocking logic to run.
    """
    from VM107.workers.task_dispatcher import run_task  # noqa: F401

    release_task = fixture_macro_release_task_docs[0]
    run_task(task=release_task, goal_service=mock_goal_service)

    mock_goal_service.on_task_completed.assert_called_once_with(
        release_task["task_id"]
    )


# ---------------------------------------------------------------------------
# Routing tests — output parsed and written to correct Mongo collection/column
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Plan 02 — parse_and_persist routing not yet implemented", strict=False)
def test_dispatcher_routes_release_analyst_to_economic_event_analysis_table(
    monkeypatch,
    mock_dispatch_agent_sync,
    fixture_macro_release_goal_doc,
):
    """release_analyst output is parsed and written to economic_event_analysis.

    Expected behaviour:
        parse_and_persist("vm107.macro_release_analyst", raw_json_str, telemetry,
                          goal_payload)
        → VM107.persistence.economic_event_analysis.insert_analysis called with
          event_id + parsed analysis dict.
    """
    from unittest.mock import MagicMock, patch

    mock_insert = MagicMock()
    with patch("VM107.persistence.economic_event_analysis.insert_analysis", mock_insert):
        from VM107.workers.task_dispatcher import parse_and_persist  # noqa: F401

        raw_json_str = '{"analysis": "CPI beat consensus by 0.1pp", "regime": "elevated_inflation"}'
        telemetry = {"tokens_used": 120, "latency_ms": 800}
        goal_payload = {"event_id": fixture_macro_release_goal_doc["payload"]["event_id"],
                        "indicator_id": "CPIAUCSL"}

        parse_and_persist(
            "vm107.macro_release_analyst",
            raw_json_str,
            telemetry,
            goal_payload,
        )

    mock_insert.assert_called_once()
    call_kwargs = mock_insert.call_args.kwargs if mock_insert.call_args.kwargs else {}
    call_args = mock_insert.call_args.args if mock_insert.call_args.args else ()
    assert goal_payload["event_id"] in str(call_args) + str(call_kwargs)


@pytest.mark.xfail(reason="Plan 02 — parse_and_persist routing not yet implemented", strict=False)
def test_dispatcher_routes_asset_exposure_to_correct_table(
    monkeypatch,
    mock_dispatch_agent_sync,
    fixture_macro_release_goal_doc,
):
    """asset_exposure_analyst output is parsed and written to economic_event_asset_exposure.

    Expected behaviour:
        parse_and_persist("vm107.macro_asset_exposure_analyst", raw_json_str, telemetry,
                          goal_payload)
        → VM107.persistence.economic_event_asset_exposure.batch_insert called with
          event_id + parsed exposures list.
    """
    from unittest.mock import MagicMock, patch

    mock_batch_insert = MagicMock()
    with patch("VM107.persistence.economic_event_asset_exposure.batch_insert", mock_batch_insert):
        from VM107.workers.task_dispatcher import parse_and_persist  # noqa: F401

        raw_json_str = '{"exposures": [{"asset": "DXY", "direction": "POS", "magnitude": 0.8}]}'
        telemetry = {"tokens_used": 110, "latency_ms": 600}
        goal_payload = {"event_id": fixture_macro_release_goal_doc["payload"]["event_id"],
                        "indicator_id": "CPIAUCSL"}

        parse_and_persist(
            "vm107.macro_asset_exposure_analyst",
            raw_json_str,
            telemetry,
            goal_payload,
        )

    mock_batch_insert.assert_called_once()
    call_args_str = str(mock_batch_insert.call_args)
    assert goal_payload["event_id"] in call_args_str or "exposures" in call_args_str


@pytest.mark.xfail(reason="Plan 02 — parse_and_persist routing not yet implemented", strict=False)
def test_dispatcher_routes_exec_summary_to_correct_column(
    monkeypatch,
    mock_dispatch_agent_sync,
    fixture_macro_release_goal_doc,
):
    """executive_summary_writer output is parsed and written to economic_event_executive_summary.

    Expected behaviour:
        parse_and_persist("vm107.macro_executive_summary_writer", raw_json_str, telemetry,
                          goal_payload)
        → VM107.persistence.economic_event_executive_summary.update_summary called with
          event_id + parsed summary string.
    """
    from unittest.mock import MagicMock, patch

    mock_update_summary = MagicMock()
    with patch("VM107.persistence.economic_event_executive_summary.update_summary", mock_update_summary):
        from VM107.workers.task_dispatcher import parse_and_persist  # noqa: F401

        raw_json_str = '{"summary": "CPI came in above consensus. DXY likely to strengthen."}'
        telemetry = {"tokens_used": 90, "latency_ms": 400}
        goal_payload = {"event_id": fixture_macro_release_goal_doc["payload"]["event_id"],
                        "indicator_id": "CPIAUCSL"}

        parse_and_persist(
            "vm107.macro_executive_summary_writer",
            raw_json_str,
            telemetry,
            goal_payload,
        )

    mock_update_summary.assert_called_once()
    call_args_str = str(mock_update_summary.call_args)
    assert goal_payload["event_id"] in call_args_str or "summary" in call_args_str


# ---------------------------------------------------------------------------
# Pitfall 2 guard — profile_id ordering before monologue
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Plan 02 — _dispatch_agent_sync not yet implemented", strict=False)
def test_dispatch_agent_sync_sets_profile_id_before_monologue(monkeypatch):
    """profile_id must be set BEFORE hist_add_user_message BEFORE monologue().

    This is the Pitfall 2 guard: slot-30 router (fail-fast) + slot-20 B1 write
    both filter on profile_id, not config.profile.  If profile_id is set after
    hist_add_user_message, the router drops the message silently.

    Ordering assertion:
        sub.set_data("profile_id", ...) called BEFORE
        sub.hist_add_user_message(...)  called BEFORE
        asyncio.run(sub.monologue())
    """
    from unittest.mock import MagicMock, call, patch

    call_order: list[str] = []

    mock_sub = MagicMock()
    mock_sub.set_data.side_effect = lambda key, val: call_order.append(f"set_data:{key}")
    mock_sub.hist_add_user_message.side_effect = lambda msg: call_order.append("hist_add_user_message")
    mock_sub.monologue = MagicMock(return_value=None)

    mock_agent_ctx = MagicMock()
    mock_agent_ctx.get.return_value = mock_sub

    with patch("VM107.workers.agent_invocation.AgentContext", mock_agent_ctx):
        import asyncio

        orig_run = asyncio.run

        def _patched_run(coro):
            call_order.append("asyncio.run(monologue)")
            return None

        with patch("asyncio.run", _patched_run):
            from VM107.workers.agent_invocation import _dispatch_agent_sync  # noqa: F401

            _dispatch_agent_sync(
                profile_id="vm107.macro_release_analyst",
                user_message="Analyze CPI release",
            )

    # Assert ordering: profile_id set BEFORE hist_add_user_message BEFORE monologue
    assert "set_data:profile_id" in call_order, "set_data(profile_id) never called"
    assert "hist_add_user_message" in call_order, "hist_add_user_message never called"
    assert "asyncio.run(monologue)" in call_order, "asyncio.run(monologue) never called"

    idx_profile = call_order.index("set_data:profile_id")
    idx_hist = call_order.index("hist_add_user_message")
    idx_monologue = call_order.index("asyncio.run(monologue)")

    assert idx_profile < idx_hist, (
        f"profile_id set (idx={idx_profile}) must come BEFORE hist_add_user_message (idx={idx_hist})"
    )
    assert idx_hist < idx_monologue, (
        f"hist_add_user_message (idx={idx_hist}) must come BEFORE monologue (idx={idx_monologue})"
    )


# ---------------------------------------------------------------------------
# DAG safety guard — blocked tasks must never run
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Plan 02 — task dispatcher not yet implemented", strict=False)
def test_dispatcher_skips_tasks_with_nonempty_blocked_by(
    mock_brain_state_collection,
    fixture_macro_release_task_docs,
):
    """Dispatcher must not pick up tasks that still have blocked_by entries.

    The exec_summary_writer starts with blocked_by=[task1_id, task2_id].
    Even if it is scanned, it must be skipped until both upstream tasks
    have completed and on_task_completed has cleared blocked_by.
    """
    from VM107.workers.task_dispatcher import get_eligible_tasks  # noqa: F401

    exec_task = fixture_macro_release_task_docs[2]
    assert exec_task["blocked_by"] != [], "Precondition: exec_summary starts blocked"

    eligible = get_eligible_tasks(collection=mock_brain_state_collection)

    eligible_ids = [t["task_id"] for t in eligible]
    assert exec_task["task_id"] not in eligible_ids, (
        "exec_summary_writer must NOT be eligible while blocked_by is non-empty"
    )
