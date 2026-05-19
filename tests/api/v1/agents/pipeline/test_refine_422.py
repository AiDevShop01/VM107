"""Phase 48 Plan 48-09 — REQ-48-D16: schema_version mismatch returns 422.

CONTEXT § Decision 16: the endpoint hard-fails on schema_version mismatch
with SchemaVersionMismatchError. Missing body fields also surface as 422.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_refine_422_on_schema_version_mismatch(
    monkeypatch, mongo_test_db, valid_hypothesis_id
) -> None:
    """``schema_version != 1`` -> 422 + SchemaVersionMismatchError detail."""
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
            "schema_version": 2,
            "async": True,
        },
        request_stub,
    )

    assert response.status_code == 422, (
        f"Expected 422; got {response.status_code}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert "SchemaVersionMismatch" in body.get("error", "") or "schema" in body.get(
        "detail", ""
    ).lower(), f"Expected SchemaVersionMismatchError in body; got {body}"


@pytest.mark.asyncio
async def test_refine_422_on_missing_hypothesis_id(
    monkeypatch, mongo_test_db
) -> None:
    """Missing ``hypothesis_id`` key -> 422 (body validation)."""
    from api.v1.agents.pipeline.refine import PipelineRefine

    monkeypatch.setattr(
        "api.v1.agents.pipeline.refine._get_db", lambda: mongo_test_db
    )

    handler = PipelineRefine(app=None, thread_lock=None)
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {"schema_version": 1, "async": True},
        request_stub,
    )

    assert response.status_code == 422
