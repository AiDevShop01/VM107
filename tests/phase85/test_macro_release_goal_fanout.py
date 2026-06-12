"""Phase 85 Plan 10 — Brain goal wrapper fan-out tests (TDD RED/GREEN).

Tests:
1. test_create_macro_release_goal_creates_three_tasks — assert 3 add_task calls
   in correct order with correct depends_on edges
2. test_idempotent_on_same_event_id — second call returns existing goal_id without
   re-invoking add_task
3. test_payload_includes_event_id_and_indicator_id — goal created with correct payload
4. test_dispatch_called_after_tasks_added — dispatch() called after all tasks added

Key design:
  create_macro_release_goal() accepts an optional ``orchestrator`` argument.
  When None, it falls back to a module-level singleton (for production use).
  Tests always pass a fresh MockBrainOrchestrator so they never hit real MongoDB/Redis.

DAG structure:
  task1 (macro_release_analyst)         — no dependencies
  task2 (macro_asset_exposure_analyst)  — no dependencies (parallel with task1)
  task3 (macro_executive_summary_writer) — depends on task1 + task2
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helper: minimal mock orchestrator matching BrainOrchestrator interface
# ---------------------------------------------------------------------------

def _make_orchestrator(existing_goal_id: str | None = None) -> MagicMock:
    """Return a mock BrainOrchestrator.

    Args:
        existing_goal_id: If set, ``find_goal_by_event_id`` returns this value
                          (simulates idempotent re-entry).
    """
    orc = MagicMock()
    orc.find_goal_by_event_id.return_value = existing_goal_id
    orc.create_goal.return_value = "goal_abc123"
    orc.add_task.side_effect = ["task_001", "task_002", "task_003"]
    return orc


# ---------------------------------------------------------------------------
# Test: three tasks created with correct dependency edges
# ---------------------------------------------------------------------------

class TestCreateMacroReleaseGoalFanout:
    """Goal wrapper creates 3 child tasks in the correct parallel + serial order."""

    def test_create_macro_release_goal_creates_three_tasks(self):
        """create_macro_release_goal must call add_task exactly 3 times."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        result_goal_id = create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        assert orc.add_task.call_count == 3, (
            f"Expected 3 add_task calls, got {orc.add_task.call_count}"
        )
        assert result_goal_id == "goal_abc123"

    def test_first_two_tasks_have_no_dependencies(self):
        """release_analyst + asset_exposure_analyst must have empty depends_on (parallel)."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        calls = orc.add_task.call_args_list
        # Task 1 — release_analyst
        t1_kwargs = calls[0][1]
        assert t1_kwargs["profile_id"] == "vm107.macro_release_analyst"
        assert t1_kwargs["depends_on"] == [], (
            f"release_analyst must have no depends_on, got {t1_kwargs['depends_on']}"
        )
        # Task 2 — asset_exposure_analyst
        t2_kwargs = calls[1][1]
        assert t2_kwargs["profile_id"] == "vm107.macro_asset_exposure_analyst"
        assert t2_kwargs["depends_on"] == [], (
            f"asset_exposure_analyst must have no depends_on, got {t2_kwargs['depends_on']}"
        )

    def test_executive_summary_writer_depends_on_first_two_tasks(self):
        """executive_summary_writer must depend on task1 + task2 (depends_on order is both)."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        calls = orc.add_task.call_args_list
        t3_kwargs = calls[2][1]
        assert t3_kwargs["profile_id"] == "vm107.macro_executive_summary_writer"
        # Must depend on both task1 and task2 (returned IDs "task_001", "task_002")
        depends_on = t3_kwargs["depends_on"]
        assert "task_001" in depends_on, f"task_003 must depend on task_001; got {depends_on}"
        assert "task_002" in depends_on, f"task_003 must depend on task_002; got {depends_on}"


# ---------------------------------------------------------------------------
# Test: payload includes event_id and indicator_id
# ---------------------------------------------------------------------------

class TestCreateMacroReleaseGoalPayload:
    """Goal created with the correct payload fields."""

    def test_payload_includes_event_id_and_indicator_id(self):
        """create_goal must be called with payload containing event_id + indicator_id."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        # create_goal called once
        assert orc.create_goal.call_count == 1
        create_kwargs = orc.create_goal.call_args[1]
        payload = create_kwargs.get("payload", {})
        assert payload.get("event_id") == "CPIAUCSL:2026-06-12T12:30:00Z", (
            f"payload.event_id mismatch: {payload}"
        )
        assert payload.get("indicator_id") == "CPIAUCSL", (
            f"payload.indicator_id mismatch: {payload}"
        )

    def test_goal_name_is_macro_release_analysis(self):
        """create_goal must use name='macro_release_analysis'."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        create_kwargs = orc.create_goal.call_args[1]
        assert create_kwargs.get("name") == "macro_release_analysis", (
            f"Expected name=macro_release_analysis, got {create_kwargs.get('name')!r}"
        )


# ---------------------------------------------------------------------------
# Test: dispatch called after all tasks added
# ---------------------------------------------------------------------------

class TestCreateMacroReleaseGoalDispatch:
    """dispatch() must be called after all 3 tasks are registered."""

    def test_dispatch_called_after_tasks_added(self):
        """dispatch must be called once, after all 3 add_task calls complete."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        call_order: list[str] = []
        orc = MagicMock()
        orc.find_goal_by_event_id.return_value = None
        orc.create_goal.return_value = "goal_abc123"

        def _add_task_side_effect(goal_id, **kwargs):
            call_order.append(f"add_task:{kwargs['profile_id']}")
            return f"task_{len(call_order):03d}"

        def _dispatch_side_effect(goal_id):
            call_order.append("dispatch")

        orc.add_task.side_effect = _add_task_side_effect
        orc.dispatch.side_effect = _dispatch_side_effect

        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        assert orc.dispatch.call_count == 1, (
            f"dispatch must be called once, got {orc.dispatch.call_count}"
        )
        # dispatch must come AFTER all 3 add_task calls
        dispatch_index = call_order.index("dispatch")
        assert dispatch_index == 3, (
            f"dispatch must be 4th call (index 3), got index {dispatch_index}; order={call_order}"
        )

    def test_dispatch_called_with_goal_id(self):
        """dispatch must be called with the goal_id returned by create_goal."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator()
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        orc.dispatch.assert_called_once_with("goal_abc123")


# ---------------------------------------------------------------------------
# Test: idempotent re-entry on same event_id
# ---------------------------------------------------------------------------

class TestCreateMacroReleaseGoalIdempotent:
    """Calling create_macro_release_goal twice for the same event_id is safe."""

    def test_idempotent_on_same_event_id(self):
        """Second call returns existing goal_id; create_goal + add_task not re-invoked."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator(existing_goal_id="goal_existing_xyz")
        result = create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        assert result == "goal_existing_xyz", (
            f"Expected existing goal_id, got {result!r}"
        )
        orc.create_goal.assert_not_called()
        orc.add_task.assert_not_called()
        orc.dispatch.assert_not_called()

    def test_idempotent_new_event_calls_create_goal(self):
        """A genuinely new event_id (find_goal_by_event_id returns None) DOES call create_goal."""
        from core.scheduling.macro_release_goal import create_macro_release_goal

        orc = _make_orchestrator(existing_goal_id=None)
        create_macro_release_goal(
            event_id="CPIAUCSL:2026-06-12T12:30:00Z",
            indicator_id="CPIAUCSL",
            orchestrator=orc,
        )

        orc.create_goal.assert_called_once()
