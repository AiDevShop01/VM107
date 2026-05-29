"""Phase 71 Wave 0 — RED tests for VM107 chat.py conversation_type routing.

These tests INTENTIONALLY fail (xfail strict) until Plan 03 ships the
`conversation_type`-aware chat endpoint that selects host agent profile +
allowed_tools per CONTEXT.md Decision 4 (hybrid 4c).

Routing table per CONTEXT.md Decision 4:
- pre_trade        -> existing pre-trade flow (default, backward compat)
- macro_chat       -> macro_agent profile
- execution_chat   -> trade_auditor_agent profile
- reflection_chat  -> reflection profile (TBD by Plan 03)
- research_chat    -> research profile (TBD by Plan 03)
- strategy_chat    -> strategy profile (TBD by Plan 03)

REQ-71-3.

Nyquist note: tests are written as xfail(strict=True) referring to a chat
client factory that does not yet exist. Plan 03 lands the endpoint extension
and the wiring; these tests become GREEN.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _post_chat(payload):
    """Stub helper — Plan 03 will replace with a real test client.

    Currently raises NotImplementedError so tests xfail loudly.
    """
    raise NotImplementedError("Plan 03 RED — chat conversation_type routing not yet wired")


@pytest.mark.xfail(reason="Plan 03 RED — conversation_type acceptance pending", strict=True)
def test_chat_accepts_conversation_type_field():
    """POST /api/v1/trades/<id>/ai/chat with conversation_type=execution_chat returns 200."""
    resp = _post_chat({
        "journal_id": "j-001",
        "message": "Why did this trade lose?",
        "conversation_type": "execution_chat",
    })
    assert resp.status_code == 200


@pytest.mark.xfail(reason="Plan 03 RED — unknown conversation_type rejection pending", strict=True)
def test_chat_unknown_conversation_type_returns_400():
    """Unknown conversation_type must be rejected with 400."""
    resp = _post_chat({
        "journal_id": "j-001",
        "message": "hello",
        "conversation_type": "invalid_mode",
    })
    assert resp.status_code == 400


@pytest.mark.xfail(reason="Plan 03 RED — execution_chat -> trade_auditor routing pending", strict=True)
def test_chat_routes_execution_chat_to_trade_auditor_profile():
    """execution_chat must bootstrap the trade_auditor_agent profile."""
    resp = _post_chat({
        "journal_id": "j-001",
        "message": "What went wrong?",
        "conversation_type": "execution_chat",
    })
    # Profile bootstrap is observable through the envelope.host_agent_id field
    # (added by Plan 03). For now we only assert the contract surface exists.
    assert resp.json().get("host_agent_id") == "trade_auditor_agent"


@pytest.mark.xfail(reason="Plan 03 RED — macro_chat -> macro_agent routing pending", strict=True)
def test_chat_routes_macro_chat_to_macro_agent_profile():
    """macro_chat must bootstrap the macro_agent profile."""
    resp = _post_chat({
        "journal_id": "j-001",
        "message": "How does the regime look?",
        "conversation_type": "macro_chat",
    })
    assert resp.json().get("host_agent_id") == "macro_agent"


@pytest.mark.xfail(reason="Plan 03 RED — default-to-pre_trade backward compat pending", strict=True)
def test_chat_defaults_to_pre_trade_when_conversation_type_omitted():
    """Omitting conversation_type must preserve the pre-Phase-71 pre_trade behavior."""
    resp = _post_chat({
        "journal_id": "j-001",
        "message": "Should I take this trade?",
    })
    assert resp.status_code == 200
    assert resp.json().get("conversation_type") == "pre_trade"
