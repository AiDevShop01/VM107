"""Phase 48 Plan 48-09 — REQ-48-D16 (V1 async-only entry contract).

POST /api/v1/agents/pipeline/refine MUST reject ``async: false`` with 422.
Refinement loops are 5-20+ minute cognition workflows; sync HTTP invocation
would distort the orchestration reality. CONTEXT § Decision 17.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_refine_rejects_async_false(
    monkeypatch, mongo_test_db, valid_hypothesis_id
) -> None:
    """``async: false`` -> 422 SchemaVersionMismatchError equivalent rejection."""
    from api.v1.agents.pipeline.refine import PipelineRefine

    monkeypatch.setattr(
        "api.v1.agents.pipeline.refine._get_db", lambda: mongo_test_db
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.scheduler_dispatch.enqueue_refinement_worker",
        MagicMock(),
    )
    monkeypatch.setattr(
        "core.events.refinement_events.emit_refinement_loop_started",
        MagicMock(),
    )

    handler = PipelineRefine(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {
            "hypothesis_id": valid_hypothesis_id,
            "schema_version": 1,
            "async": False,
        },
        request_stub,
    )

    assert response.status_code == 422, (
        f"Expected 422 for async=false; got {response.status_code}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert "async" in body.get("detail", "").lower() or "async" in body.get(
        "error", ""
    ).lower(), f"Expected async-rejection detail; got {body}"


@pytest.mark.asyncio
async def test_refine_accepts_async_true(
    monkeypatch, mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash
) -> None:
    """Happy path: ``async: true`` -> 202 + {task_id, loop_id, started_at}."""
    from api.v1.agents.pipeline.refine import PipelineRefine
    from core.agents.refinement_orchestrator import state as _state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        _state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )
    monkeypatch.setattr(
        "api.v1.agents.pipeline.refine._get_db", lambda: mongo_test_db
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.scheduler_dispatch.enqueue_refinement_worker",
        MagicMock(),
    )
    monkeypatch.setattr(
        "core.events.refinement_events.emit_refinement_loop_started",
        MagicMock(),
    )

    handler = PipelineRefine(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {
            "hypothesis_id": valid_hypothesis_id,
            "schema_version": 1,
            "async": True,
        },
        request_stub,
    )

    assert response.status_code == 202, (
        f"Expected 202 for async=true; got {response.status_code} "
        f"body={response.get_data(as_text=True)}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert "task_id" in body, f"Expected task_id in body; got {body}"
    assert "loop_id" in body, f"Expected loop_id in body; got {body}"
    assert "started_at" in body, f"Expected started_at in body; got {body}"
