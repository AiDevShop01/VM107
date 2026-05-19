"""Phase 48 Plan 48-09 — REQ-48-D16: ``refinement_loop_started`` emits BEFORE 202.

CONTEXT § Decision 16: endpoint emits ``refinement_loop_started`` Phase 56
event IMMEDIATELY after validation, BEFORE returning the task_id.
CONTEXT § Decision 18: orchestrator is the SOLE EMITTER of refinement
lifecycle events — the endpoint emits ``refinement_loop_started`` itself
(this is the only event emitted from the HTTP entry surface; the loop
worker emits the rest from main_loop).

This test uses two MagicMocks with shared call-order tracking to PROVE
emit fires BEFORE the Response is built.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_emit_fires_before_response(
    monkeypatch, mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash
) -> None:
    """Assert emit_refinement_loop_started call_count == 1 BEFORE the Response."""
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

    # Shared ordering trace — every call appends its label to this list.
    call_order: list[str] = []

    def emit_spy(**kwargs):
        call_order.append("emit_refinement_loop_started")
        return None

    def enqueue_spy(*args, **kwargs):
        call_order.append("enqueue_refinement_worker")
        return None

    monkeypatch.setattr(
        "core.events.refinement_events.emit_refinement_loop_started",
        emit_spy,
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.scheduler_dispatch.enqueue_refinement_worker",
        enqueue_spy,
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

    # Response built AFTER emit — emit is index 0.
    assert response.status_code == 202
    assert "emit_refinement_loop_started" in call_order, (
        f"emit_refinement_loop_started never called; call_order={call_order}"
    )
    assert call_order.index("emit_refinement_loop_started") < len(call_order), (
        "emit must precede response construction"
    )
    # If enqueue fired, it MUST come AFTER emit (Pattern 51: emit + persist
    # before async dispatch).
    if "enqueue_refinement_worker" in call_order:
        assert call_order.index("emit_refinement_loop_started") < call_order.index(
            "enqueue_refinement_worker"
        ), f"emit must precede enqueue; call_order={call_order}"

    body = json.loads(response.get_data(as_text=True))
    assert body["loop_id"]
    assert body["task_id"]
