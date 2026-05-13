"""Unit tests for the Phase 60.1 Agent Zero subordinate invocation adapter.

Tests cover:
  - test_marshal_input_round_trip: Pydantic input marshalled as JSON UserMessage
  - test_unmarshal_json_dict: valid JSON monologue output parsed to dict
  - test_invalid_json_raises_typed_error: non-JSON monologue raises MentorSubordinateInvokerError
  - test_history_new_topic_called: history.new_topic() called exactly once after monologue
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ConfigDict

from helpers import mentor_subordinate_invoker as msi


class _FakeInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    execution_id: str
    scope_origin: str


def _make_fake_subordinate(monologue_returns: str) -> MagicMock:
    fake = MagicMock()
    fake.monologue = AsyncMock(return_value=monologue_returns)
    fake.hist_add_user_message = MagicMock()
    fake.history = MagicMock()
    return fake


@pytest.mark.asyncio
async def test_marshal_input_round_trip(monkeypatch):
    """Pydantic input is serialised as JSON inside UserMessage.message."""
    captured = {}

    def _capture(msg):
        # UserMessage(message=..., attachments=...)
        captured["message"] = msg.message

    sub = _make_fake_subordinate(monologue_returns=json.dumps({"ok": True}))
    sub.hist_add_user_message = MagicMock(side_effect=_capture)

    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    inp = _FakeInput(execution_id="abc", scope_origin="test")
    out = await msi.invoke_mentor_subordinate("trade_auditor_agent._reader", inp)

    assert out == {"ok": True}
    assert json.loads(captured["message"]) == {"execution_id": "abc", "scope_origin": "test"}


@pytest.mark.asyncio
async def test_unmarshal_json_dict(monkeypatch):
    """Valid JSON string from monologue is parsed and returned as dict."""
    scripted = {"schema_version": "1.0", "execution_id": "00000000-0000-0000-0000-000000000001"}
    sub = _make_fake_subordinate(monologue_returns=json.dumps(scripted))
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    out = await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )
    assert isinstance(out, dict)
    assert out == scripted


@pytest.mark.asyncio
async def test_invalid_json_raises_typed_error(monkeypatch):
    """Non-JSON monologue output raises MentorSubordinateInvokerError with raw_output attached."""
    sub = _make_fake_subordinate(monologue_returns="sorry I cannot do that")
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    with pytest.raises(msi.MentorSubordinateInvokerError) as exc_info:
        await msi.invoke_mentor_subordinate(
            "trade_auditor_agent._reader",
            _FakeInput(execution_id="x", scope_origin="t"),
        )

    assert exc_info.value.raw_output == "sorry I cannot do that"


@pytest.mark.asyncio
async def test_history_new_topic_called(monkeypatch):
    """history.new_topic() is called exactly once after a successful monologue."""
    sub = _make_fake_subordinate(monologue_returns=json.dumps({"ok": True}))
    new_topic = MagicMock()
    sub.history.new_topic = new_topic
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )
    assert new_topic.call_count == 1


# 60-23: Agent Zero response-tool unwrap tests
@pytest.mark.asyncio
async def test_response_tool_wrap_unwraps_inner_json(monkeypatch):
    """When monologue returns {tool_name: response, tool_args: {text: '<json>'}},
    invoker unwraps and returns the inner parsed JSON."""
    inner_payload = {
        "schema_version": "1.0",
        "execution_id": None,
        "retrieved_evidence": {},
        "suspicious_payload": [],
    }
    wrapped = {
        "thoughts": ["reasoning..."],
        "headline": "Reader done",
        "tool_name": "response",
        "tool_args": {"text": json.dumps(inner_payload)},
    }
    sub = _make_fake_subordinate(monologue_returns=json.dumps(wrapped))
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    result = await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )

    assert result == inner_payload
    assert "tool_name" not in result
    assert "tool_args" not in result


@pytest.mark.asyncio
async def test_response_tool_wrap_prose_returns_sentinel(monkeypatch):
    """When tool_args.text is prose (not JSON), invoker returns a sentinel dict
    so downstream model_validate fails with a recognizable error."""
    wrapped = {
        "tool_name": "response",
        "tool_args": {"text": "Reader stage initialized but no evidence available."},
    }
    sub = _make_fake_subordinate(monologue_returns=json.dumps(wrapped))
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    result = await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )

    assert "_unwrapped_prose" in result
    assert result["_unwrapped_prose"].startswith("Reader stage initialized")
    assert "_orig_tool_call" in result


@pytest.mark.asyncio
async def test_response_tool_missing_text_passes_through(monkeypatch):
    """When response tool has no `text` field, the original dict passes through
    unchanged (downstream model_validate fails normally)."""
    wrapped = {
        "tool_name": "response",
        "tool_args": {"something_else": "value"},
    }
    sub = _make_fake_subordinate(monologue_returns=json.dumps(wrapped))
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    result = await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )

    assert result == wrapped


@pytest.mark.asyncio
async def test_raw_json_envelope_unchanged_regression(monkeypatch):
    """Regression guard: when monologue returns raw ReaderOutput JSON (not wrapped
    in response tool), invoker returns it unchanged (backward compat with profiles
    that already comply)."""
    raw_envelope = {
        "schema_version": "1.0",
        "execution_id": "abc-123",
        "retrieved_evidence": {"source": "test"},
        "suspicious_payload": [],
    }
    sub = _make_fake_subordinate(monologue_returns=json.dumps(raw_envelope))
    monkeypatch.setattr(msi, "_SUBORDINATE_FACTORY", lambda profile: sub)

    result = await msi.invoke_mentor_subordinate(
        "trade_auditor_agent._reader",
        _FakeInput(execution_id="x", scope_origin="t"),
    )

    assert result == raw_envelope
