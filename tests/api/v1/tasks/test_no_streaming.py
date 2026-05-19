"""Phase 48 Plan 48-09 — REQ-48-D17: GET /api/v1/tasks polling MUST NOT stream.

CONTEXT § Decision 17: "Polling MUST NOT stream raw agent thoughts. Loop is
bounded orchestration state, NOT interactive chat."

This test:
1. Asserts response is plain JSON (Content-Type: application/json).
2. Walks the response payload and asserts no key matches the forbidden set
   {prompt, completion, response_text, thoughts, refinement_targets,
    rationale, agent_envelopes, llm_output, raw_response}.
3. Asserts no nested dict is deeper than 1 level (flat state-machine shape;
   ``budget_snapshot`` and similar nested helpers are flattened on serialize).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


_FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "completion",
        "response_text",
        "thoughts",
        "refinement_targets",
        "rationale",
        "agent_envelopes",
        "llm_output",
        "raw_response",
        "critic_verdict",
        "strategy_spec",
        "code_module",
        "backtest_result",
        "build_report",
    }
)


def _seed(db, *, snapshot_hash):
    now = datetime.now(tz=timezone.utc).isoformat()
    doc = {
        "_id": "loop_streaming_test",
        "loop_id": "loop_streaming_test",
        "task_id": "task_streaming_test",
        "root_hypothesis_id": "hyp_streaming_test",
        "strategy_family": "BREAKOUT",
        "loop_registry_snapshot_hash": snapshot_hash,
        "iteration": 1,
        "max_iterations": 3,
        "iteration_artifact_ids": [
            # Trajectory index — opaque IDs only, NEVER prose.
            {"iter": 0, "strategy_spec_id": "spec_0",
             "code_module_id": "code_0", "critic_verdict_id": "verdict_0"},
        ],
        "strategy_version": "0.1.0",
        "code_version": "0.1.0",
        "critic_history": ["verdict_0"],
        "veto_history": [],
        "identity_scores": [0.95],
        "refinement_delta_history": [],
        "budget_snapshot": {
            "loop_budget_remaining_usd": 3.5,
            "iteration_budget_remaining_usd": 1.0,
        },
        "termination_reason": None,
        "started_at": now,
        "updated_at": now,
        "spec_iter0_id": "spec_0",
        "schema_version": 1,
    }
    db["refinement_loops"].insert_one(doc)


def _assert_no_forbidden_keys(payload, *, path="root") -> None:
    """Recurse and assert no key in payload matches forbidden set."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            assert k not in _FORBIDDEN_KEYS, (
                f"Forbidden streaming-content key {k!r} found at {path}"
            )
            _assert_no_forbidden_keys(v, path=f"{path}.{k}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_no_forbidden_keys(item, path=f"{path}[{i}]")


@pytest.mark.asyncio
async def test_polling_returns_plain_json_not_streaming(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash
) -> None:
    """Plain JSON Content-Type, no SSE / chunked / streaming."""
    from api.v1.tasks.get_task import GetTask

    monkeypatch.setattr(
        "api.v1.tasks.get_task._get_db", lambda: mongo_test_db
    )

    _seed(mongo_test_db, snapshot_hash=frozen_registry_snapshot_hash)

    handler = GetTask(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {"task_id": "task_streaming_test"}

    response = await handler.process({}, request_stub)
    assert response.status_code == 200
    assert response.mimetype == "application/json", (
        f"Expected application/json, got {response.mimetype}"
    )
    # No streaming-content keys allowed anywhere in payload.
    body = json.loads(response.get_data(as_text=True))
    _assert_no_forbidden_keys(body)


@pytest.mark.asyncio
async def test_polling_payload_is_flat_state_machine(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash
) -> None:
    """Polling shape carries opaque IDs and primitive metrics — never prose."""
    from api.v1.tasks.get_task import GetTask

    monkeypatch.setattr(
        "api.v1.tasks.get_task._get_db", lambda: mongo_test_db
    )
    _seed(mongo_test_db, snapshot_hash=frozen_registry_snapshot_hash)

    handler = GetTask(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {"task_id": "task_streaming_test"}

    response = await handler.process({}, request_stub)
    body = json.loads(response.get_data(as_text=True))

    # Every top-level value must be a primitive (str, int, float, bool, None)
    # OR a single-level dict of primitives (budget_remaining_usd may be a
    # number, current_stage is a string, etc.).
    for key, value in body.items():
        if isinstance(value, dict):
            for nk, nv in value.items():
                assert not isinstance(nv, (dict, list)), (
                    f"Polling payload has nested-dict-deeper-than-1 at "
                    f"{key}.{nk}: {type(nv).__name__}"
                )
        # Lists are permitted only for opaque ID arrays (no prose).
        elif isinstance(value, list):
            for item in value:
                assert isinstance(item, (str, int, float, bool, type(None))), (
                    f"Polling payload list at {key} carries non-primitive: "
                    f"{type(item).__name__}"
                )


# ---------------------------------------------------------------------------
# ReplayQueryService extension — snapshot-hash HARD FAIL (Decision 15).
# ---------------------------------------------------------------------------


def test_replay_query_service_extension_hard_fails_on_snapshot_mismatch(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash
) -> None:
    """CONTEXT § Decision 15: replay against a different snapshot = HARD FAIL.

    The Phase 56 ReplayQueryService extension validates the stored snapshot
    hash against the live CapabilityRegistry; mismatch raises
    SnapshotMismatchError immediately. No "best-effort replay".
    """
    from core.events.replay_query_service_extension import (
        get_refinement_timeline,
    )
    from core.events.phase56_client import SnapshotMismatchError

    # Seed a loop with stored_hash="A".
    _seed(mongo_test_db, snapshot_hash="snapshot_hash_A")

    # Live registry returns "B" — mismatch.
    from core.events import replay_query_service_extension as _ext

    class _FakeReg:
        snapshot_hash = "snapshot_hash_B"

    monkeypatch.setattr(
        _ext.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )
    monkeypatch.setattr(
        "core.events.replay_query_service_extension._get_db",
        lambda: mongo_test_db,
    )

    with pytest.raises(SnapshotMismatchError):
        get_refinement_timeline(loop_id="loop_streaming_test")


def test_replay_query_service_extension_returns_ordered_timeline(
    monkeypatch, mongo_test_db, frozen_registry_snapshot_hash
) -> None:
    """Happy path: snapshot match -> returns events ordered by occurred_at."""
    from core.events.replay_query_service_extension import (
        get_refinement_timeline,
    )

    _seed(mongo_test_db, snapshot_hash=frozen_registry_snapshot_hash)

    # Seed deterministic events into the test "events" collection
    # (Phase 56 stub: extension reads via Mongo until VM100 read API exists).
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    events = [
        {
            "event_type": "refinement_loop_started",
            "correlation_id": "loop_streaming_test",
            "occurred_at": "2026-01-01T00:00:00Z",
            "payload": {"loop_id": "loop_streaming_test"},
        },
        {
            "event_type": "iteration_started",
            "correlation_id": "loop_streaming_test",
            "occurred_at": "2026-01-01T00:00:01Z",
            "payload": {"loop_id": "loop_streaming_test", "iteration_number": 0},
        },
        {
            "event_type": "loop_terminated",
            "correlation_id": "loop_streaming_test",
            "occurred_at": "2026-01-01T00:00:02Z",
            "payload": {"loop_id": "loop_streaming_test"},
        },
    ]
    mongo_test_db["events"].insert_many(events)

    from core.events import replay_query_service_extension as _ext

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        _ext.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )
    monkeypatch.setattr(
        "core.events.replay_query_service_extension._get_db",
        lambda: mongo_test_db,
    )

    timeline = get_refinement_timeline(loop_id="loop_streaming_test")
    assert len(timeline) == 3
    # Ordering preserved.
    assert [e["event_type"] for e in timeline] == [
        "refinement_loop_started", "iteration_started", "loop_terminated",
    ]
