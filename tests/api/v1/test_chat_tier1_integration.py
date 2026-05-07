"""Phase 47.2-07 — Chat handler Tier-1 integration.

Target module: api.v1.trades.ai.chat
Plan 07 graduates Plan 01's xfail stubs by:
  - making the chat handler IGNORE inline `context` payload from VM100
  - calling build_tier1_context(journal_id) server-side instead
  - threading the Tier-1 dict into _build_user_prompt

These specs prove:
  1. test_inline_context_ignored — _build_user_prompt receives Tier-1 dict
     (REAL data), NOT the inline FAKE payload.
  2. test_inline_context_not_passed_to_prompt — the value bound to `context`
     in process() is build_tier1_context(journal_id)'s result.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


_FAKE_TIER1 = {
    "trade_id": "trade-1",
    "instrument": "REAL_INSTRUMENT",
    "direction": "short",
    "strategy_id": "model_2_option_1_short",
    "last_evaluation": None,
    "journal_metadata": {
        "timeframe": "M5",
        "checklist_snapshot_text": "real snapshot",
        "entry_price": 1.10,
        "stop_loss_price": 1.11,
        "take_profit_price": 1.09,
    },
}


def _make_flask_app():
    """Minimal Flask test app mirroring production dispatch (X-API-KEY gate)."""
    from flask import Flask, request as flask_request

    app = Flask("test_chat_tier1_integration")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _chat_dispatch(journal_id: str):
        from api.v1.trades.ai.chat import TradeAiChat
        from helpers.api import requires_api_key

        instance = TradeAiChat(app, lock)

        async def _call():
            return await instance.handle_request(request=flask_request)

        return await requires_api_key(_call)()

    app.add_url_rule(
        "/api/v1/trades/<journal_id>/ai/chat",
        "trade_ai_chat",
        _chat_dispatch,
        methods=["POST"],
    )
    return app


def _mock_envelope(**kwargs):
    """Stand-in for build_envelope that returns a MagicMock with the right attrs."""
    env = MagicMock()
    env.task_id = kwargs["task_id"]
    env.envelope_id = "env-test-id"
    env.journal_id = kwargs.get("journal_id")
    env.status = kwargs["status"]
    env.input = kwargs["input_payload"]
    env.output = kwargs["output_payload"]
    return env


def test_inline_context_ignored():
    """POST chat with inline {context: {instrument: 'FAKE'}}. Tier-1 patched
    to return REAL data. _build_user_prompt MUST receive the Tier-1 dict
    (REAL), not the inline FAKE payload."""
    captured = {}

    def _capture_prompt(message, context, journal_id):
        captured["message"] = message
        captured["context"] = context
        captured["journal_id"] = journal_id
        return "rendered prompt"

    app = _make_flask_app()

    with patch(
        "helpers.settings.get_settings",
        return_value={"mcp_server_token": "test-key"},
    ), patch(
        "api.v1.trades.ai.chat.get_mongo_db",
        return_value=MagicMock(
            **{
                "__getitem__.return_value": MagicMock(
                    find_one=MagicMock(return_value=None),
                    find=MagicMock(return_value=iter([])),
                    insert_one=MagicMock(),
                )
            }
        ),
    ), patch(
        "api.v1.trades.ai.chat.build_envelope",
        side_effect=_mock_envelope,
    ), patch(
        "api.v1.trades.ai.chat.write_envelope",
        return_value="env-test-id",
    ), patch(
        "api.v1.trades.ai.chat.build_tier1_context",
        new=AsyncMock(return_value=dict(_FAKE_TIER1)),
    ), patch(
        "api.v1.trades.ai.chat._build_user_prompt",
        side_effect=_capture_prompt,
    ), patch(
        "api.v1.trades.ai.chat._call_coordinator_monologue",
        new=AsyncMock(return_value=("ok", {"fallback_used": False})),
    ):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/journal-xyz/ai/chat",
                data=json.dumps(
                    {
                        "message": "What do you think?",
                        # Inline context that MUST be ignored:
                        "context": {"instrument": "FAKE_INSTRUMENT"},
                    }
                ),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 200, rv.data
    # _build_user_prompt was invoked with the Tier-1 result, not inline.
    assert captured["context"] == _FAKE_TIER1
    assert captured["context"]["instrument"] == "REAL_INSTRUMENT"
    # Inline FAKE_INSTRUMENT must not have leaked into prompt build.
    assert captured["context"]["instrument"] != "FAKE_INSTRUMENT"


def test_inline_context_not_passed_to_prompt():
    """Even when the request omits inline context entirely, the chat handler
    still binds context to build_tier1_context(journal_id)'s return value."""
    captured = {}

    def _capture_prompt(message, context, journal_id):
        captured["context"] = context
        captured["journal_id"] = journal_id
        return "rendered prompt"

    tier1_mock = AsyncMock(return_value=dict(_FAKE_TIER1))

    app = _make_flask_app()

    with patch(
        "helpers.settings.get_settings",
        return_value={"mcp_server_token": "test-key"},
    ), patch(
        "api.v1.trades.ai.chat.get_mongo_db",
        return_value=MagicMock(
            **{
                "__getitem__.return_value": MagicMock(
                    find_one=MagicMock(return_value=None),
                    find=MagicMock(return_value=iter([])),
                    insert_one=MagicMock(),
                )
            }
        ),
    ), patch(
        "api.v1.trades.ai.chat.build_envelope",
        side_effect=_mock_envelope,
    ), patch(
        "api.v1.trades.ai.chat.write_envelope",
        return_value="env-test-id",
    ), patch(
        "api.v1.trades.ai.chat.build_tier1_context",
        new=tier1_mock,
    ), patch(
        "api.v1.trades.ai.chat._build_user_prompt",
        side_effect=_capture_prompt,
    ), patch(
        "api.v1.trades.ai.chat._call_coordinator_monologue",
        new=AsyncMock(return_value=("ok", {"fallback_used": False})),
    ):
        with app.test_client() as client:
            rv = client.post(
                "/api/v1/trades/journal-xyz/ai/chat",
                data=json.dumps({"message": "Is this short valid?"}),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    assert rv.status_code == 200, rv.data
    # Tier-1 builder MUST have been invoked exactly once with journal_id.
    tier1_mock.assert_awaited_once_with("journal-xyz")
    # The dict passed to _build_user_prompt is Tier-1's return value.
    assert captured["context"] == _FAKE_TIER1
    assert captured["journal_id"] == "journal-xyz"
