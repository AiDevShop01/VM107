"""Phase 48 Plan 48-09 — REQ-48-D17: GET /api/v1/tasks/{task_id} response shape.

CONTEXT § Decision 17: polling response carries ONLY state-machine fields —
NO raw agent thoughts, NO LLM responses, NO refinement_targets prose.
The endpoint maps RefinementLoopState.termination_reason + iteration state
to RefinementTaskState (9-state enum from Decision 17).

Polling shape (CONTEXT.md verbatim):
    {
      "task_id": "...",
      "state": "REFINING",
      "current_iteration": 2,
      "current_stage": "BACKTESTER",
      "budget_remaining_usd": 4.12,
      "started_at": "...",
      "updated_at": "...",
      "termination_reason": null,
      "loop_id": "...",
      "loop_registry_snapshot_hash": "..."
    }

Implementation note (Plan 09 deviation Rule 3 — Blocking):
helpers/api.py register_api_route() uses ``/api/<path:path>`` greedy
matching — curly-brace path parameters are NOT supported by the existing
dispatcher. The endpoint accepts ``?task_id=X`` query parameter instead;
the path remains ``GET /api/v1/tasks/get_task``. This matches the existing
VM107 file-based dispatch pattern.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _seed_loop_state(
    db, *, loop_id: str, task_id: str, snapshot_hash: str,
    iteration: int = 0, termination_reason: str | None = None,
    strategy_family: str = "BREAKOUT",
):
    """Insert a minimum-shape RefinementLoopState doc for polling tests."""
    now = datetime.now(tz=timezone.utc).isoformat()
    doc = {
        "_id": loop_id,
        "loop_id": loop_id,
        "task_id": task_id,
        "root_hypothesis_id": "hyp_test_001",
        "strategy_family": strategy_family,
        "loop_registry_snapshot_hash": snapshot_hash,
        "iteration": iteration,
        "max_iterations": 3,
        "iteration_artifact_ids": [],
        "strategy_version": "0.0.0",
        "code_version": "0.0.0",
        "critic_history": [],
        "veto_history": [],
        "identity_scores": [],
        "refinement_delta_history": [],
        "budget_snapshot": {"loop_budget_remaining_usd": 4.12},
        "termination_reason": termination_reason,
        "started_at": now,
        "updated_at": now,
        "spec_iter0_id": None,
        "schema_version": 1,
    }
    db["refinement_loops"].insert_one(doc)
    return doc


@pytest.mark.asyncio
async def test_get_task_returns_state_machine_shape(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash
) -> None:
    """RUNNING / REFINING / ACCEPTED / REJECTED states map deterministically."""
    from api.v1.tasks.get_task import GetTask

    monkeypatch.setattr(
        "api.v1.tasks.get_task._get_db", lambda: mongo_test_db
    )

    _seed_loop_state(
        mongo_test_db,
        loop_id="loop_test_001",
        task_id="task_test_001",
        snapshot_hash=frozen_registry_snapshot_hash,
        iteration=2,
        termination_reason=None,
    )

    handler = GetTask(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {"task_id": "task_test_001"}

    response = await handler.process({}, request_stub)
    assert response.status_code == 200, response.get_data(as_text=True)
    body = json.loads(response.get_data(as_text=True))

    # 10 required state-machine keys (Decision 17 shape).
    expected_keys = {
        "task_id", "state", "current_iteration", "current_stage",
        "budget_remaining_usd", "started_at", "updated_at",
        "termination_reason", "loop_id", "loop_registry_snapshot_hash",
    }
    assert set(body.keys()) >= expected_keys, (
        f"Missing keys: {expected_keys - set(body.keys())}; got {list(body.keys())}"
    )
    assert body["task_id"] == "task_test_001"
    assert body["loop_id"] == "loop_test_001"
    assert body["current_iteration"] == 2
    assert body["state"] == "REFINING"  # iter > 0 + no termination -> REFINING
    assert body["termination_reason"] is None


@pytest.mark.asyncio
async def test_get_task_404_on_unknown_task(monkeypatch, mongo_test_db) -> None:
    """Unknown task_id -> 404."""
    from api.v1.tasks.get_task import GetTask

    monkeypatch.setattr(
        "api.v1.tasks.get_task._get_db", lambda: mongo_test_db
    )

    handler = GetTask(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {"task_id": "task_does_not_exist"}

    response = await handler.process({}, request_stub)
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "termination_reason,expected_state",
    [
        ("ACCEPTED", "ACCEPTED"),
        ("CRITIC_REJECT", "REJECTED"),
        ("HARD_VETO", "REJECTED"),
        ("MAX_ITERATIONS", "REJECTED"),
        ("CONVERGENCE_STALL", "CONVERGENCE_STALL"),
        ("IDENTITY_DRIFT", "IDENTITY_DRIFT"),
        ("BUDGET_EXCEEDED_ITERATION", "BUDGET_EXCEEDED"),
        ("BUDGET_EXCEEDED_LOOP", "BUDGET_EXCEEDED"),
        ("BUILD_FAILURE", "FAILED"),
        ("BUILD_FAILED", "FAILED"),
        ("STRATEGY_DEGRADED", "FAILED"),
        ("CODE_DEGRADED", "FAILED"),
        ("BACKTEST_DEGRADED", "FAILED"),
        ("CRITIC_DEGRADED", "FAILED"),
    ],
)
async def test_get_task_termination_to_state_mapping(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash,
    termination_reason, expected_state,
) -> None:
    """Decision 17 — every TerminationReason maps to a defined RefinementTaskState."""
    from api.v1.tasks.get_task import GetTask

    monkeypatch.setattr(
        "api.v1.tasks.get_task._get_db", lambda: mongo_test_db
    )

    task_id = f"task_{termination_reason.lower()}"
    _seed_loop_state(
        mongo_test_db,
        loop_id=f"loop_{termination_reason.lower()}",
        task_id=task_id,
        snapshot_hash=frozen_registry_snapshot_hash,
        iteration=1,
        termination_reason=termination_reason,
    )

    handler = GetTask(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {"task_id": task_id}
    response = await handler.process({}, request_stub)
    body = json.loads(response.get_data(as_text=True))
    assert body["state"] == expected_state, (
        f"termination_reason={termination_reason} -> expected state="
        f"{expected_state}, got {body['state']}"
    )
