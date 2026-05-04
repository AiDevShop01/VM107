"""
Phase 47-05 — Tests for VM107 trade AI chat handler.

POST /api/v1/trades/<journal_id>/ai/chat
- X-API-KEY required (401 without)
- Empty message body → 422
- journal_id read from request.view_args
- Successful LLM call → envelope persisted with journal_id + status="success", 200
- LLM failure → envelope persisted with status="failure", 502
- Fallback fired → response has degraded=True, envelope status="degraded"
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

def _make_flask_app():
    """Create a minimal Flask test app with trade-ai chat URL registered.

    Mirrors the production ui_server.register_http_routes() dispatch pattern
    including X-API-KEY authentication gate (requires_api_key decorator).
    """
    from flask import Flask, request as flask_request
    import threading

    app = Flask("test_trade_ai_chat")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _chat_dispatch(journal_id: str):
        from api.v1.trades.ai.chat import TradeAiChat
        from helpers.api import requires_api_key
        instance = TradeAiChat(app, lock)

        async def _call():
            return await instance.handle_request(request=flask_request)

        # Apply X-API-KEY gate (mirrors production dispatch in ui_server.py).
        return await requires_api_key(_call)()

    app.add_url_rule(
        "/api/v1/trades/<journal_id>/ai/chat",
        "trade_ai_chat",
        _chat_dispatch,
        methods=["POST"],
    )
    return app


def _api_key_headers():
    return {"X-API-KEY": "test-key", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# test_api_key_required
# ---------------------------------------------------------------------------

def test_api_key_required():
    """POST chat without X-API-KEY header returns 401."""
    app = _make_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/j1/ai/chat",
                data=json.dumps({"message": "Is this setup valid?"}),
                content_type="application/json",
            )
    assert rv.status_code == 401


# ---------------------------------------------------------------------------
# test_empty_message_422
# ---------------------------------------------------------------------------

def test_empty_message_422():
    """POST chat with empty message body returns 422."""
    app = _make_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/j1/ai/chat",
                data=json.dumps({"message": ""}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )
    assert rv.status_code == 422
    body = json.loads(rv.data)
    assert "error" in body


# ---------------------------------------------------------------------------
# test_journal_id_extracted_from_url
# ---------------------------------------------------------------------------

def test_journal_id_extracted_from_url():
    """Handler reads journal_id from request.view_args['journal_id'] and uses it in envelope."""
    persisted = []

    def mock_write(db, env):
        persisted.append(env)
        return env.envelope_id

    def mock_build(**kwargs):
        from core.contracts.envelope import AgentEnvelope
        return AgentEnvelope(
            task_id=kwargs["task_id"],
            parent_task_id=None,
            agent_id=kwargs["agent_id"],
            input=kwargs["input_payload"],
            output=kwargs["output_payload"],
            model_used=kwargs.get("telemetry", {}).get("model_used", "unknown"),
            cost={},
            reason_chain=[],
            source_envelope_id=kwargs.get("source_envelope_id"),
            journal_id=kwargs.get("journal_id"),
            status=kwargs["status"],
        )

    app = _make_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}), \
         patch("api.v1.trades.ai.chat.get_mongo_db", return_value=MagicMock(
             **{"__getitem__.return_value": MagicMock(find_one=MagicMock(return_value=None), insert_one=MagicMock())}
         )), \
         patch("api.v1.trades.ai.chat.build_envelope", side_effect=mock_build), \
         patch("api.v1.trades.ai.chat.write_envelope", side_effect=mock_write), \
         patch("api.v1.trades.ai.chat._call_llm_direct", new=AsyncMock(return_value=("The setup looks valid.", {}))):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/journal-abc/ai/chat",
                data=json.dumps({"message": "Is this trade valid?"}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 200
    assert len(persisted) == 1
    assert persisted[0].journal_id == "journal-abc"


# ---------------------------------------------------------------------------
# test_success_envelope_persisted
# ---------------------------------------------------------------------------

def test_success_envelope_persisted():
    """Successful chat persists exactly one envelope with journal_id, status='success'."""
    persisted = []

    def mock_write(db, env):
        persisted.append(env)
        return env.envelope_id

    def mock_build(**kwargs):
        from core.contracts.envelope import AgentEnvelope
        return AgentEnvelope(
            task_id=kwargs["task_id"],
            parent_task_id=None,
            agent_id=kwargs["agent_id"],
            input=kwargs["input_payload"],
            output=kwargs["output_payload"],
            model_used=kwargs.get("telemetry", {}).get("model_used", "unknown"),
            cost={},
            reason_chain=[],
            source_envelope_id=kwargs.get("source_envelope_id"),
            journal_id=kwargs.get("journal_id"),
            status=kwargs["status"],
        )

    app = _make_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}), \
         patch("api.v1.trades.ai.chat.get_mongo_db", return_value=MagicMock(
             **{"__getitem__.return_value": MagicMock(find_one=MagicMock(return_value=None), insert_one=MagicMock())}
         )), \
         patch("api.v1.trades.ai.chat.build_envelope", side_effect=mock_build), \
         patch("api.v1.trades.ai.chat.write_envelope", side_effect=mock_write), \
         patch("api.v1.trades.ai.chat._call_llm_direct", new=AsyncMock(return_value=("Good setup.", {}))):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/j1/ai/chat",
                data=json.dumps({"message": "Is this trade valid?", "context": {"instrument": "EURUSD"}}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 200
    body = json.loads(rv.data)
    assert body["status"] == "success"
    assert body["degraded"] is False
    assert "envelope_id" in body
    assert "response" in body

    assert len(persisted) == 1
    env = persisted[0]
    assert env.journal_id == "j1"
    assert env.status == "success"
    assert env.input.get("message") == "Is this trade valid?"


# ---------------------------------------------------------------------------
# test_failure_envelope_on_llm_error
# ---------------------------------------------------------------------------

def test_failure_envelope_on_llm_error():
    """LLM failure persists an envelope with status='failure' and returns 502."""
    persisted = []

    def mock_write(db, env):
        persisted.append(env)
        return env.envelope_id

    def mock_build(**kwargs):
        from core.contracts.envelope import AgentEnvelope
        return AgentEnvelope(
            task_id=kwargs["task_id"],
            parent_task_id=None,
            agent_id=kwargs["agent_id"],
            input=kwargs["input_payload"],
            output=kwargs["output_payload"],
            model_used=kwargs.get("telemetry", {}).get("model_used", "unknown"),
            cost={},
            reason_chain=[],
            source_envelope_id=kwargs.get("source_envelope_id"),
            journal_id=kwargs.get("journal_id"),
            status=kwargs["status"],
        )

    app = _make_flask_app()

    async def _raise(*args, **kwargs):
        raise RuntimeError("LLM chain exhausted")

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}), \
         patch("api.v1.trades.ai.chat.get_mongo_db", return_value=MagicMock(
             **{"__getitem__.return_value": MagicMock(find_one=MagicMock(return_value=None), insert_one=MagicMock())}
         )), \
         patch("api.v1.trades.ai.chat.build_envelope", side_effect=mock_build), \
         patch("api.v1.trades.ai.chat.write_envelope", side_effect=mock_write), \
         patch("api.v1.trades.ai.chat._call_llm_direct", side_effect=_raise):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/j1/ai/chat",
                data=json.dumps({"message": "Is this trade valid?"}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 502
    body = json.loads(rv.data)
    assert body["status"] == "failure"
    assert "envelope_id" in body

    assert len(persisted) == 1
    assert persisted[0].status == "failure"
    assert persisted[0].journal_id == "j1"


# ---------------------------------------------------------------------------
# test_degraded_flag
# ---------------------------------------------------------------------------

def test_degraded_flag():
    """Fallback fired → response has degraded=true and envelope status='degraded'."""
    persisted = []

    def mock_write(db, env):
        persisted.append(env)
        return env.envelope_id

    def mock_build(**kwargs):
        from core.contracts.envelope import AgentEnvelope
        return AgentEnvelope(
            task_id=kwargs["task_id"],
            parent_task_id=None,
            agent_id=kwargs["agent_id"],
            input=kwargs["input_payload"],
            output=kwargs["output_payload"],
            model_used=kwargs.get("telemetry", {}).get("model_used", "unknown"),
            cost={},
            reason_chain=[],
            source_envelope_id=kwargs.get("source_envelope_id"),
            journal_id=kwargs.get("journal_id"),
            status=kwargs["status"],
        )

    app = _make_flask_app()

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}), \
         patch("api.v1.trades.ai.chat.get_mongo_db", return_value=MagicMock(
             **{"__getitem__.return_value": MagicMock(find_one=MagicMock(return_value=None), insert_one=MagicMock())}
         )), \
         patch("api.v1.trades.ai.chat.build_envelope", side_effect=mock_build), \
         patch("api.v1.trades.ai.chat.write_envelope", side_effect=mock_write), \
         patch("api.v1.trades.ai.chat._call_llm_direct",
               new=AsyncMock(return_value=("Fallback response.", {"fallback_used": True}))):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/j1/ai/chat",
                data=json.dumps({"message": "Is this setup valid?"}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 200
    body = json.loads(rv.data)
    assert body["degraded"] is True
    assert body["status"] == "degraded"

    assert len(persisted) == 1
    assert persisted[0].status == "degraded"
