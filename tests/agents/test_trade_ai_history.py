"""
Phase 47-05 — Tests for VM107 trade AI history handler.

GET /api/v1/trades/<journal_id>/ai/history
- Returns {messages: [], journal_id: str}
- Messages ordered chronologically ascending by timestamp
- Empty list when journal has no envelopes
- Each envelope produces two messages: user + agent
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flask_app_history():
    """Create a minimal Flask test app with the history URL registered."""
    from flask import Flask, request as flask_request
    import threading

    app = Flask("test_trade_ai_history")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _history_dispatch(journal_id: str):
        from api.v1.trades.ai.history import TradeAiHistory
        from helpers.api import requires_api_key
        instance = TradeAiHistory(app, lock)

        async def _call():
            return await instance.handle_request(request=flask_request)

        return await requires_api_key(_call)()

    app.add_url_rule(
        "/api/v1/trades/<journal_id>/ai/history",
        "trade_ai_history",
        _history_dispatch,
        methods=["GET"],
    )
    return app


def _make_envelope_doc(
    envelope_id: str,
    journal_id: str,
    message: str,
    response: str,
    status: str = "success",
    timestamp: datetime | None = None,
) -> dict:
    """Build a minimal agent_envelopes document for test fixtures."""
    ts = timestamp or datetime.now(timezone.utc)
    return {
        "_id": envelope_id,
        "envelope_id": envelope_id,
        "journal_id": journal_id,
        "agent_id": "agent_zero",
        "input": {"message": message, "context": {}},
        "output": {"response": response} if status != "failure" else {"error": "LLM failed"},
        "status": status,
        "timestamp": ts,
        "task_id": f"chat-{envelope_id}",
        "model_used": "deepseek/deepseek-v4-flash",
        "cost": {},
        "reason_chain": [],
        "schema_version": 1,
    }


# ---------------------------------------------------------------------------
# test_messages_ordered
# ---------------------------------------------------------------------------

def test_messages_ordered():
    """GET history returns messages in chronological order (ascending timestamp)."""
    base = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    env1 = _make_envelope_doc("env1", "j1", "First message", "First reply", timestamp=base)
    env2 = _make_envelope_doc("env2", "j1", "Second message", "Second reply", timestamp=base + timedelta(seconds=5))
    env3 = _make_envelope_doc("env3", "j1", "Third message", "Third reply", timestamp=base + timedelta(seconds=10))

    # Deliver them out of order to test sorting
    docs = [env3, env1, env2]

    from api.v1.trades.ai.history import TradeAiHistory
    import threading

    app_mock = MagicMock()
    lock = threading.RLock()
    handler = TradeAiHistory(app_mock, lock)

    # Build a mock mongo collection that returns docs in insertion order
    # (not sorted) — handler must sort by timestamp ascending.
    col = MagicMock()
    col.find.return_value = iter(docs)

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: col if name == "agent_envelopes" else MagicMock())

    from unittest.mock import patch, MagicMock as MM, AsyncMock
    from flask import Flask, request as flask_request
    import asyncio

    test_app = Flask("test_order")
    with test_app.test_request_context(
        "/api/v1/trades/j1/ai/history",
        method="GET",
    ) as ctx:
        ctx.request.view_args = {"journal_id": "j1"}

        with patch("api.v1.trades.ai.history.get_mongo_db", return_value=db):
            result = asyncio.get_event_loop().run_until_complete(
                handler.process({}, flask_request)
            )

    body = json.loads(result.response[0])
    messages = body["messages"]

    # 3 envelopes × 2 messages each = 6
    assert len(messages) == 6

    # Verify chronological order by checking user message contents
    user_messages = [m["content"] for m in messages if m["role"] == "user"]
    assert user_messages == ["First message", "Second message", "Third message"]


# ---------------------------------------------------------------------------
# test_empty_for_new_journal
# ---------------------------------------------------------------------------

def test_empty_for_new_journal():
    """GET history for a journal with no envelopes returns {messages: [], journal_id: j99}."""
    from api.v1.trades.ai.history import TradeAiHistory
    import threading

    app_mock = MagicMock()
    lock = threading.RLock()
    handler = TradeAiHistory(app_mock, lock)

    col = MagicMock()
    col.find.return_value = iter([])

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: col if name == "agent_envelopes" else MagicMock())

    from unittest.mock import patch
    from flask import Flask, request as flask_request
    import asyncio

    test_app = Flask("test_empty")
    with test_app.test_request_context(
        "/api/v1/trades/j99/ai/history",
        method="GET",
    ) as ctx:
        ctx.request.view_args = {"journal_id": "j99"}

        with patch("api.v1.trades.ai.history.get_mongo_db", return_value=db):
            result = asyncio.get_event_loop().run_until_complete(
                handler.process({}, flask_request)
            )

    body = json.loads(result.response[0])
    assert body["messages"] == []
    assert body["journal_id"] == "j99"
