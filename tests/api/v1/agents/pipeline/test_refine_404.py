"""Phase 48 Plan 48-09 — REQ-48-D16: unknown hypothesis_id returns 404.

CONTEXT § Decision 6: Hypothesis-id-in entry contract. The endpoint MUST
verify the hypothesis exists in the ``hypotheses`` collection BEFORE
allocating a loop_id / task_id or emitting any lifecycle events.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_refine_404_on_unknown_hypothesis(
    monkeypatch, mongo_test_db
) -> None:
    """``hypothesis_id`` not in ``hypotheses`` collection -> 404 + no events."""
    from api.v1.agents.pipeline.refine import PipelineRefine

    monkeypatch.setattr(
        "api.v1.agents.pipeline.refine._get_db", lambda: mongo_test_db
    )

    mock_enqueue = MagicMock()
    mock_emit = MagicMock()
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.scheduler_dispatch.enqueue_refinement_worker",
        mock_enqueue,
    )
    monkeypatch.setattr(
        "core.events.refinement_events.emit_refinement_loop_started",
        mock_emit,
    )

    handler = PipelineRefine(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {
            "hypothesis_id": "hyp_does_not_exist_xyz",
            "schema_version": 1,
            "async": True,
        },
        request_stub,
    )

    assert response.status_code == 404, (
        f"Expected 404 for unknown hypothesis_id; got {response.status_code}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert "hyp_does_not_exist_xyz" in body.get(
        "detail", ""
    ) or "hyp_does_not_exist_xyz" in body.get("error", ""), (
        f"Expected echoed hypothesis_id in error; got {body}"
    )
    # No side effects on 404 — neither dispatch nor emit fired.
    assert mock_enqueue.call_count == 0
    assert mock_emit.call_count == 0
