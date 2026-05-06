"""
Phase 47.1-04 — Tests for VM107 trade AI evaluation endpoint.

POST /api/v1/trades/{journal_id}/ai/evaluation
- X-API-KEY required (401 without)
- journal_id read from request.view_args (parametric URL)
- EvaluationContractViolation → 502 with envelope_id in body
- Missing conversation_id → 422
- Successful runner call → 200 with {evaluation, envelope_id, evaluation_id}

Graduated from Wave 0 xfail stubs (47.1-01) to real assertions (47.1-04 / Task 1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evaluation_flask_app():
    """Create a minimal Flask test app with trade-ai evaluation URL registered.

    Mirrors the production ui_server.register_http_routes() dispatch pattern
    including X-API-KEY authentication gate (requires_api_key decorator).
    """
    from flask import Flask, request as flask_request
    import threading

    app = Flask("test_trade_ai_evaluation")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _evaluation_dispatch(journal_id: str):
        from api.v1.trades.ai.evaluation import TradeAiEvaluation
        from helpers.api import requires_api_key

        instance = TradeAiEvaluation(app, lock)

        async def _call():
            return await instance.handle_request(request=flask_request)

        return await requires_api_key(_call)()

    app.add_url_rule(
        "/api/v1/trades/<journal_id>/ai/evaluation",
        "trade_ai_evaluation",
        _evaluation_dispatch,
        methods=["POST"],
    )
    return app


def _api_key_headers():
    return {"X-API-KEY": "test-key", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Test 1: X-API-KEY required — 401 without header
# ---------------------------------------------------------------------------

def test_api_key_required():
    """POST evaluation without X-API-KEY header returns 401.

    CONTEXT-vm107-endpoint requirement (auth gate).
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    app = _make_evaluation_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/journal-x/ai/evaluation",
                data=json.dumps({"conversation_id": "c", "user_id": "u"}),
                content_type="application/json",
            )
            assert rv.status_code == 401


# ---------------------------------------------------------------------------
# Test 2: journal_id extracted from URL view_args
# ---------------------------------------------------------------------------

def test_journal_id_extracted_from_url():
    """POST to /api/v1/trades/test-journal-uuid/ai/evaluation.

    Handler reads journal_id from request.view_args (parametric URL pattern).
    A missing journal_id is detected early; here we verify the handler reaches
    field validation (not URL mismatch), confirming journal_id WAS extracted.

    Mirrors Phase 47-05 chat handler URL extraction pattern.
    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    app = _make_evaluation_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        # Missing conversation_id: if journal_id is correctly extracted, we get 422
        # (field validation), not 404 or URL error.
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/test-journal-uuid/ai/evaluation",
                data=json.dumps({"user_id": "u"}),  # no conversation_id
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )
            # 422 = journal_id extracted OK; handler reached field validation
            assert rv.status_code == 422
            body = rv.get_json()
            assert "conversation_id" in (body.get("error") or "")


# ---------------------------------------------------------------------------
# Test 3: EvaluationContractViolation → 502
# ---------------------------------------------------------------------------

def test_502_on_contract_violation():
    """Mock run_pre_trade_evaluation to raise EvaluationContractViolation.

    Asserts: response 502, body has error="EvaluationContractViolation" and envelope_id.
    Verifies the endpoint honours the fail-fast principle (no silent fallback).

    CONTEXT-vm107-endpoint + CONTEXT-fail-fast requirements.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    from core.agents.invocation_exceptions import EvaluationContractViolation

    app = _make_evaluation_flask_app()

    async def _fake_runner(**kwargs):
        exc = EvaluationContractViolation(
            error_chain=["attempt 1 plain text", "attempt 2 plain text"],
            envelope_id="env-fail-123",
        )
        raise exc

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with patch("api.v1.trades.ai.evaluation.run_pre_trade_evaluation", side_effect=_fake_runner):
            with patch("api.v1.trades.ai.evaluation.get_mongo_db", return_value=MagicMock()):
                with app.test_client() as client:
                    rv = client.post(
                        "/api/v1/trades/journal-x/ai/evaluation",
                        data=json.dumps({"conversation_id": "c", "user_id": "u"}),
                        content_type="application/json",
                        headers={"X-API-KEY": "test-key"},
                    )
                    assert rv.status_code == 502
                    body = rv.get_json()
                    assert body["error"] == "EvaluationContractViolation"
                    assert body["envelope_id"] == "env-fail-123"


# ---------------------------------------------------------------------------
# Test 4: Missing conversation_id → 422
# ---------------------------------------------------------------------------

def test_422_missing_conversation_id():
    """POST without conversation_id field in request body → 422.

    conversation_id is required per the endpoint contract (CONTEXT.md § Endpoint
    Contracts). The endpoint must validate input before invoking the runner.

    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    app = _make_evaluation_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/journal-x/ai/evaluation",
                data=json.dumps({"user_id": "u"}),  # no conversation_id
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )
            assert rv.status_code == 422
            body = rv.get_json()
            assert "conversation_id" in (body.get("error") or "")


# ---------------------------------------------------------------------------
# Test 5: Successful run → 200 with evaluation dict
# ---------------------------------------------------------------------------

def test_success_200():
    """Mock runner returns valid evaluation.

    Asserts: response 200 with keys {evaluation, envelope_id, evaluation_id}.
    Matches VM107 endpoint contract (CONTEXT.md § Endpoint Contracts).

    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    from core.contracts.schemas import PreTradeEvaluation

    fake_eval = PreTradeEvaluation(
        instrument="EUR/USD",
        direction="long",
        recommendation="enter",
        confidence=0.7,
        score=78,
        check_results={"htf_alignment": "pass"},
        reasoning_summary="Setup looks good.",
        risks=["spread widening"],
        invalidations=["price closes below 1.0800"],
        next_action="Enter long at market open.",
    )
    # Inject system fields (mirrors what the runner does post safe_parse)
    fake_eval = fake_eval.model_copy(update={"evaluation_id": "uuid-test-1"})

    async def _fake_runner(**kwargs):
        return (fake_eval, "env-success-99", "task-abc")

    app = _make_evaluation_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with patch("api.v1.trades.ai.evaluation.run_pre_trade_evaluation", side_effect=_fake_runner):
            with patch("api.v1.trades.ai.evaluation.get_mongo_db", return_value=MagicMock()):
                with app.test_client() as client:
                    rv = client.post(
                        "/api/v1/trades/journal-x/ai/evaluation",
                        data=json.dumps({
                            "conversation_id": "conv-123",
                            "user_id": "user-456",
                            "strategy_id": "model-2",
                            "context": {"instrument": "EUR/USD", "timeframe": "H1"},
                        }),
                        content_type="application/json",
                        headers={"X-API-KEY": "test-key"},
                    )
                    assert rv.status_code == 200
                    body = rv.get_json()
                    assert "evaluation" in body
                    assert "envelope_id" in body
                    assert "evaluation_id" in body
                    assert body["evaluation_id"] == "uuid-test-1"
                    assert body["envelope_id"] == "env-success-99"
                    assert body["evaluation"]["instrument"] == "EUR/USD"
