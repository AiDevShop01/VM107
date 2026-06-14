"""Factory functions for Phase 85.1 brain_state fixture documents.

Provides Python-native dict factories that mirror the shape of documents
stored in the ``vm107_brain.brain_state`` MongoDB collection.  Used by
conftest.py and directly in tests that need a controlled starting state.

Shape references:
- GoalModel (core.scheduling.models) — goal_id, task_ids, payload, goal_type, status
- Task dict (core.scheduling.macro_release_goal.BrainOrchestrator.add_task output)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def make_goal_doc(
    goal_id: str,
    indicator_id: str,
    event_id: str,
    title: str = "macro_release_analysis",
    status: str = "active",
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return a dict matching the vm107_brain.brain_state goal row shape.

    Args:
        goal_id: Unique goal identifier (e.g. "goal_abc123").
        indicator_id: FRED series code (e.g. "CPIAUCSL").
        event_id: Release event ID (e.g. "evt_CPIAUCSL_2026_06_14").
        title: Human-readable goal name; defaults to "macro_release_analysis".
        status: GoalStatus value; defaults to "active".
        task_ids: Optional list of task IDs; defaults to empty list.

    Returns:
        dict matching brain_state goal document shape.
    """
    now = datetime.now(timezone.utc)
    return {
        "goal_id": goal_id,
        "title": f"{title}: {indicator_id}",
        "description": (
            f"Macro release analysis for event_id={event_id}, "
            f"indicator={indicator_id}"
        ),
        "goal_type": "MAINTENANCE",
        "status": status,
        "priority": "P2",
        "objective_label": "macro_intelligence",
        "decomposition_template": None,
        "created_by": "vm107.macro_release_event_listener",
        "governance_tier": "auto",
        "budget_max_cost_usd": None,
        "budget_max_tokens": None,
        "task_ids": task_ids if task_ids is not None else [],
        "payload": {
            "event_id": event_id,
            "indicator_id": indicator_id,
        },
        "failure_reason": None,
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
    }


def make_task_doc(
    task_id: str,
    goal_id: str,
    agent_name: str,
    blocked_by: list[str] | None = None,
    status: str = "pending",
    retry_count: int = 0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Return a dict matching the vm107_brain.brain_state task row shape.

    Args:
        task_id: Unique task identifier (e.g. "task_abc123").
        goal_id: Parent goal identifier.
        agent_name: Agent profile_id string (e.g. "vm107.macro_release_analyst").
        blocked_by: List of task_ids this task is blocked on; defaults to [].
        status: TaskStatus value; defaults to "pending".
        retry_count: Current retry count; defaults to 0.
        max_retries: Maximum retries allowed; defaults to 3.

    Returns:
        dict matching brain_state task document shape.
    """
    now = datetime.now(timezone.utc)
    deps = blocked_by if blocked_by is not None else []
    return {
        "task_id": task_id,
        "goal_id": goal_id,
        "task_type": "analysis",
        "status": status,
        "priority": "P2",
        "agent_name": agent_name,
        "dependencies": list(deps),
        "blocked_by": list(deps),
        "preemptible": False,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "failure_reason": None,
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
    }


def make_macro_release_goal_with_three_tasks(
    indicator_id: str = "CPIAUCSL",
    event_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create a canonical macro_release_analysis goal with 3 tasks.

    DAG structure:
        release_analyst_task  (no deps — runs immediately)
        asset_exposure_task   (no deps — runs in parallel)
        exec_summary_task     (blocked_by=[release_id, asset_id] — runs after both)

    Args:
        indicator_id: FRED series code; defaults to "CPIAUCSL".
        event_id: Release event ID; auto-generated if None.

    Returns:
        Tuple of (goal_doc, [release_analyst_task, asset_exposure_task, exec_summary_task]).
        exec_summary_task['blocked_by'] == [release_analyst_task['task_id'], asset_exposure_task['task_id']]
    """
    if event_id is None:
        event_id = f"evt_{indicator_id}_2026_06_14"

    goal_id = f"goal_{uuid.uuid4().hex[:12]}"
    release_task_id = f"task_{uuid.uuid4().hex[:12]}"
    asset_task_id = f"task_{uuid.uuid4().hex[:12]}"
    exec_task_id = f"task_{uuid.uuid4().hex[:12]}"

    release_analyst_task = make_task_doc(
        task_id=release_task_id,
        goal_id=goal_id,
        agent_name="vm107.macro_release_analyst",
        blocked_by=[],
        status="pending",
    )

    asset_exposure_task = make_task_doc(
        task_id=asset_task_id,
        goal_id=goal_id,
        agent_name="vm107.macro_asset_exposure_analyst",
        blocked_by=[],
        status="pending",
    )

    exec_summary_task = make_task_doc(
        task_id=exec_task_id,
        goal_id=goal_id,
        agent_name="vm107.macro_executive_summary_writer",
        blocked_by=[release_task_id, asset_task_id],
        status="blocked",
    )

    goal_doc = make_goal_doc(
        goal_id=goal_id,
        indicator_id=indicator_id,
        event_id=event_id,
        status="active",
        task_ids=[release_task_id, asset_task_id, exec_task_id],
    )

    return goal_doc, [release_analyst_task, asset_exposure_task, exec_summary_task]
