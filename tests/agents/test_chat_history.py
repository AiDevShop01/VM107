"""
Phase 47-05 — History reconstruction tests (graduated from Wave 0 xfail stubs).

Covers:
- Chronological ordering of history messages
- Failure envelope placeholders ('[ Response failed — AI service error]')
- source_envelope_id chaining across successive chat turns
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import threading
import asyncio

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope_doc(
    envelope_id: str,
    journal_id: str,
    message: str,
    response: str,
    status: str = "success",
    timestamp: datetime | None = None,
    source_envelope_id: str | None = None,
) -> dict:
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
        "source_envelope_id": source_envelope_id,
    }


# ---------------------------------------------------------------------------
# test_history_ordered
# ---------------------------------------------------------------------------

def test_history_ordered():
    """History reconstruction returns envelopes ordered by timestamp ascending."""
    base = datetime(2026, 5, 4, 9, 0, 0, tzinfo=timezone.utc)
    env_a = _make_envelope_doc("envA", "j1", "Msg A", "Reply A", timestamp=base)
    env_b = _make_envelope_doc("envB", "j1", "Msg B", "Reply B", timestamp=base + timedelta(seconds=30))
    env_c = _make_envelope_doc("envC", "j1", "Msg C", "Reply C", timestamp=base + timedelta(seconds=60))

    # Provide out of order — handler must sort ascending
    docs = [env_c, env_a, env_b]

    from api.v1.trades.ai.history import TradeAiHistory
    from flask import Flask, request as flask_request

    handler = TradeAiHistory(MagicMock(), threading.RLock())
    col = MagicMock()
    col.find.return_value = iter(docs)
    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda n: col if n == "agent_envelopes" else MagicMock())

    app = Flask("t_ord")
    with app.test_request_context("/api/v1/trades/j1/ai/history", method="GET") as ctx:
        ctx.request.view_args = {"journal_id": "j1"}
        with patch("api.v1.trades.ai.history.get_mongo_db", return_value=db):
            result = asyncio.get_event_loop().run_until_complete(
                handler.process({}, flask_request)
            )

    body = json.loads(result.response[0])
    msgs = body["messages"]
    user_msgs = [m["content"] for m in msgs if m["role"] == "user"]
    assert user_msgs == ["Msg A", "Msg B", "Msg C"]


# ---------------------------------------------------------------------------
# test_history_includes_failures
# ---------------------------------------------------------------------------

def test_history_includes_failures():
    """Failure envelopes appear with '[Response failed — AI service error]' and failed: True."""
    base = datetime(2026, 5, 4, 9, 0, 0, tzinfo=timezone.utc)
    env_ok = _make_envelope_doc("envOK", "j2", "Good question", "Good answer", timestamp=base)
    env_fail = _make_envelope_doc(
        "envFAIL", "j2", "This will fail", "",
        status="failure",
        timestamp=base + timedelta(seconds=10),
    )

    from api.v1.trades.ai.history import TradeAiHistory
    from flask import Flask, request as flask_request

    handler = TradeAiHistory(MagicMock(), threading.RLock())
    col = MagicMock()
    col.find.return_value = iter([env_ok, env_fail])
    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda n: col if n == "agent_envelopes" else MagicMock())

    app = Flask("t_fail")
    with app.test_request_context("/api/v1/trades/j2/ai/history", method="GET") as ctx:
        ctx.request.view_args = {"journal_id": "j2"}
        with patch("api.v1.trades.ai.history.get_mongo_db", return_value=db):
            result = asyncio.get_event_loop().run_until_complete(
                handler.process({}, flask_request)
            )

    body = json.loads(result.response[0])
    msgs = body["messages"]

    # 2 envelopes × 2 messages = 4
    assert len(msgs) == 4

    # Find the failure agent message
    fail_agent_msgs = [
        m for m in msgs
        if m["role"] == "agent" and m.get("failed") is True
    ]
    assert len(fail_agent_msgs) == 1
    assert fail_agent_msgs[0]["content"] == "[Response failed — AI service error]"
    assert fail_agent_msgs[0]["failed"] is True


# ---------------------------------------------------------------------------
# test_source_envelope_id_chain
# ---------------------------------------------------------------------------

def test_source_envelope_id_chain():
    """Second chat envelope has source_envelope_id == first envelope's envelope_id."""
    # Use the TradeAiChat handler to make two successive "turns" and verify
    # the second envelope chains to the first.
    from api.v1.trades.ai.chat import TradeAiChat
    from flask import Flask, request as flask_request

    journal_id = "chain-j1"
    persisted: list = []

    # Simulate a Mongo collection that:
    # - find_one returns None (for prev lookup) on first call
    # - find_one returns the first persisted doc on second call
    # - insert_one appends to persisted list
    call_count = {"find_one": 0}

    def _find_one(query, sort=None):
        call_count["find_one"] += 1
        if call_count["find_one"] == 1:
            return None  # first turn — no prior envelope
        # second turn — return first persisted doc (simulate DB state)
        for doc in persisted:
            if doc.get("journal_id") == journal_id:
                return doc
        return None

    def _insert_one(doc):
        persisted.append(doc)

    col = MagicMock()
    col.find_one = _find_one
    col.insert_one = _insert_one

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda n: col if n == "agent_envelopes" else MagicMock())

    handler = TradeAiChat(MagicMock(), threading.RLock())
    app = Flask("t_chain")

    # First turn
    with app.test_request_context(
        f"/api/v1/trades/{journal_id}/ai/chat",
        method="POST",
        json={"message": "First question", "context": {}},
    ) as ctx:
        ctx.request.view_args = {"journal_id": journal_id}
        with patch("api.v1.trades.ai.chat.get_mongo_db", return_value=db), \
             patch("api.v1.trades.ai.chat._call_llm_direct",
                   new=AsyncMock(return_value=("First response", {}))):
            asyncio.get_event_loop().run_until_complete(
                handler.process({"message": "First question", "context": {}}, flask_request)
            )

    assert len(persisted) == 1
    first_env_id = persisted[0]["envelope_id"]

    # Second turn
    with app.test_request_context(
        f"/api/v1/trades/{journal_id}/ai/chat",
        method="POST",
        json={"message": "Second question", "context": {}},
    ) as ctx:
        ctx.request.view_args = {"journal_id": journal_id}
        with patch("api.v1.trades.ai.chat.get_mongo_db", return_value=db), \
             patch("api.v1.trades.ai.chat._call_llm_direct",
                   new=AsyncMock(return_value=("Second response", {}))):
            asyncio.get_event_loop().run_until_complete(
                handler.process({"message": "Second question", "context": {}}, flask_request)
            )

    assert len(persisted) == 2
    second_env = persisted[1]
    assert second_env["source_envelope_id"] == first_env_id, (
        f"Expected source_envelope_id={first_env_id!r}, got {second_env.get('source_envelope_id')!r}"
    )
    assert second_env["journal_id"] == journal_id
