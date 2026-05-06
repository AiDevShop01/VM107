"""
Phase 47.1-01 — Wave 0 xfail scaffolding for VM107 trade AI evaluation endpoint.

Tests specification for POST /api/v1/trades/{journal_id}/ai/evaluation (Flask ApiHandler).
All tests are xfail (Wave 0) until Plan 47.1-04 ships the target endpoint.

Graduated to GREEN by: 47.1-04 / Task 1
Target modules:
  - api.v1.trades.ai.evaluation (ApiHandler)
  - core.agents.invocation_exceptions (EvaluationContractViolation)

Test count: 5 (per 47.1-VALIDATION.md Per-Task Verification Map)
  1. test_api_key_required
  2. test_journal_id_extracted_from_url
  3. test_502_on_contract_violation
  4. test_422_missing_conversation_id
  5. test_success_200

Pattern: mirrors test_trade_ai_chat.py (Phase 47-05) — Flask test_client +
  X-API-KEY gate + async dispatch wrapper.
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
    Will be implemented when Plan 47.1-04 ships api.v1.trades.ai.evaluation.
    """
    from flask import Flask, request as flask_request
    import threading

    app = Flask("test_trade_ai_evaluation")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _evaluation_dispatch(journal_id: str):
        from api.v1.trades.ai.evaluation import TradeAiEvaluation  # noqa: F401
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

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-04 implements api.v1.trades.ai.evaluation")
def test_api_key_required():
    """POST evaluation without X-API-KEY header returns 401.

    CONTEXT-vm107-endpoint requirement (auth gate).
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    pytest.fail("Wave 0 stub — implement in Plan 47.1-04")


# ---------------------------------------------------------------------------
# Test 2: journal_id extracted from URL view_args
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-04 implements api.v1.trades.ai.evaluation")
def test_journal_id_extracted_from_url():
    """POST to /api/v1/trades/test-journal-uuid/ai/evaluation.

    Handler reads journal_id from request.view_args (parametric URL pattern).
    Mirrors Phase 47-05 chat handler URL extraction pattern.

    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    pytest.fail("Wave 0 stub — implement in Plan 47.1-04")


# ---------------------------------------------------------------------------
# Test 3: EvaluationContractViolation → 502
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-04 implements api.v1.trades.ai.evaluation")
def test_502_on_contract_violation():
    """Mock run_pre_trade_evaluation to raise EvaluationContractViolation.

    Asserts: response 502, body has error="EvaluationContractViolation".
    Verifies the endpoint honours the fail-fast principle (no silent fallback).

    CONTEXT-vm107-endpoint + CONTEXT-fail-fast requirements.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    from core.agents.invocation_exceptions import EvaluationContractViolation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-04")


# ---------------------------------------------------------------------------
# Test 4: Missing conversation_id → 422
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-04 implements api.v1.trades.ai.evaluation")
def test_422_missing_conversation_id():
    """POST without conversation_id field in request body → 422.

    conversation_id is required per the endpoint contract (CONTEXT.md § Endpoint
    Contracts). The endpoint must validate input before invoking the runner.

    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    pytest.fail("Wave 0 stub — implement in Plan 47.1-04")


# ---------------------------------------------------------------------------
# Test 5: Successful run → 200 with evaluation dict
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-04 implements api.v1.trades.ai.evaluation")
def test_success_200():
    """Mock runner returns valid evaluation.

    Asserts: response 200 with keys {evaluation, envelope_id, evaluation_id}.
    Matches VM107 endpoint contract (CONTEXT.md § Endpoint Contracts).

    CONTEXT-vm107-endpoint requirement.
    Graduated to GREEN by: 47.1-04 / Task 1
    """
    pytest.fail("Wave 0 stub — implement in Plan 47.1-04")
