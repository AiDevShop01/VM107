"""Phase 71 Plan 02 — GREEN tests for VM107 chat.py conversation_type routing.

Plan 00 (Wave 0) scaffolded these as RED xfail stubs against a non-existent
`_post_chat` helper. Plan 02 flips them green by wiring a real Flask test
client (same pattern as tests/api/v1/test_chat_tier1_integration.py) that
exercises the actual `TradeAiChat` handler with the host-agent monologue
mocked out.

Routing table per CONTEXT.md Decision 4:

- pre_trade        -> agent0 (Phase 47 default; backward compat when omitted)
- macro_chat       -> macro_agent
- execution_chat   -> trade_auditor_agent
- reflection_chat  -> behavioral_mentor_agent
- strategy_chat    -> weekly_review_agent
- research_chat    -> research_chat_agent

REQ-71-3.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# chat.py requires CHAT_MODEL at import time. Set a safe sentinel before any
# load. Production overrides this via container env; tests need it stubbed.
os.environ.setdefault("CHAT_MODEL", "test-model")

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _load_chat_module():
    """Load chat.py by absolute path (namespace-package shadowing workaround).

    The tests/ tree contains tests/api/v1/__init__.py which Python's import
    system treats as the same `api.v1` package as the production code. This
    shadowing prevents `from api.v1.trades.ai import chat`. Mirror the
    pattern used by tests/api/v1/test_chat_tier1_integration.py.
    """
    import importlib.util

    chat_path = _VM107_ROOT / "api" / "v1" / "trades" / "ai" / "chat.py"
    spec = importlib.util.spec_from_file_location("_chat_under_test_p71", chat_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FAKE_TIER1 = {
    "trade_id": "trade-1",
    "instrument": "EURUSD",
    "direction": "long",
    "strategy_id": "model_1_option_2_long",
    "last_evaluation": None,
    "journal_metadata": {
        "timeframe": "M15",
        "checklist_snapshot_text": "snapshot",
        "entry_price": 1.10,
        "stop_loss_price": 1.09,
        "take_profit_price": 1.12,
    },
}


def _make_flask_app(chat_module):
    """Minimal Flask test app mirroring production dispatch (X-API-KEY gate)."""
    from flask import Flask, request as flask_request

    app = Flask("test_chat_conversation_type")
    app.config["TESTING"] = True
    lock = threading.RLock()

    async def _chat_dispatch(journal_id: str):
        from helpers.api import requires_api_key

        instance = chat_module.TradeAiChat(app, lock)

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
    """Stand-in for build_envelope returning a MagicMock with the right attrs."""
    env = MagicMock()
    env.task_id = kwargs["task_id"]
    env.envelope_id = "env-test-id"
    env.journal_id = kwargs.get("journal_id")
    env.status = kwargs["status"]
    env.input = kwargs["input_payload"]
    env.output = kwargs["output_payload"]
    return env


def _mongo_db_stub():
    """Stand-in for the Mongo db handle: empty find/find_one."""
    return MagicMock(
        **{
            "__getitem__.return_value": MagicMock(
                find_one=MagicMock(return_value=None),
                find=MagicMock(return_value=iter([])),
                insert_one=MagicMock(),
            )
        }
    )


def _post_chat(payload, journal_id="j-001"):
    """Helper: dispatch a POST through the real Flask test client.

    Mocks the host-agent runtime so tests don't require a live LLM —
    asserts profile_name routing + conversation_type plumbing only.

    Returns the Flask test response object.
    """
    chat_module = _load_chat_module()
    captured: dict = {}

    async def _capture_monologue(
        chat_evaluator_addendum,
        user_prompt,
        history_envelopes,
        profile_name="agent0",
        conversation_type=None,
    ):
        captured["profile_name"] = profile_name
        captured["conversation_type"] = conversation_type
        return "mocked response", {
            "model_used": "test-model",
            "fallback_used": False,
            "host_agent_id": profile_name,
            "conversation_type": conversation_type,
        }

    app = _make_flask_app(chat_module)

    with patch("helpers.settings.get_settings", return_value={"mcp_server_token": "test-key"}), \
         patch.object(chat_module, "get_mongo_db", return_value=_mongo_db_stub()), \
         patch.object(chat_module, "build_envelope", side_effect=_mock_envelope), \
         patch.object(chat_module, "write_envelope", return_value="env-test-id"), \
         patch.object(chat_module, "build_tier1_context", new=AsyncMock(return_value=dict(_FAKE_TIER1))), \
         patch.object(chat_module, "_call_coordinator_monologue", side_effect=_capture_monologue):
        with app.test_client() as client:
            rv = client.post(
                f"/api/v1/trades/{journal_id}/ai/chat",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-API-KEY": "test-key"},
            )

    # Attach captured routing decision for caller inspection.
    rv._captured = captured  # type: ignore[attr-defined]
    return rv


def test_chat_accepts_conversation_type_field():
    """POST chat with conversation_type=execution_chat returns 200."""
    resp = _post_chat({
        "message": "Why did this trade lose?",
        "conversation_type": "execution_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["conversation_type"] == "execution_chat"


def test_chat_unknown_conversation_type_returns_400():
    """Unknown conversation_type must be rejected with 400 (not 500)."""
    resp = _post_chat({
        "message": "hello",
        "conversation_type": "invalid_mode",
    })
    assert resp.status_code == 400, resp.data
    body = json.loads(resp.data)
    assert body["error"] == "invalid_conversation_type"
    assert "invalid_mode" in body["detail"]


def test_chat_routes_execution_chat_to_trade_auditor_profile():
    """execution_chat must bootstrap the trade_auditor_agent profile."""
    resp = _post_chat({
        "message": "What went wrong?",
        "conversation_type": "execution_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "trade_auditor_agent"
    # Verify the routing actually reached the monologue invocation.
    assert resp._captured["profile_name"] == "trade_auditor_agent"  # type: ignore[attr-defined]
    assert resp._captured["conversation_type"] == "execution_chat"  # type: ignore[attr-defined]


def test_chat_routes_macro_chat_to_macro_agent_profile():
    """macro_chat must bootstrap the macro_agent profile."""
    resp = _post_chat({
        "message": "How does the regime look?",
        "conversation_type": "macro_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "macro_agent"
    assert resp._captured["profile_name"] == "macro_agent"  # type: ignore[attr-defined]


def test_chat_routes_reflection_chat_to_behavioral_mentor_profile():
    """reflection_chat must bootstrap the behavioral_mentor_agent profile."""
    resp = _post_chat({
        "message": "What pattern did I repeat?",
        "conversation_type": "reflection_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "behavioral_mentor_agent"


def test_chat_routes_strategy_chat_to_weekly_review_profile():
    """strategy_chat must bootstrap the weekly_review_agent profile."""
    resp = _post_chat({
        "message": "Review my week",
        "conversation_type": "strategy_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "weekly_review_agent"


def test_chat_routes_research_chat_to_research_chat_profile():
    """research_chat must bootstrap the research_chat_agent profile."""
    resp = _post_chat({
        "message": "Show me similar patterns",
        "conversation_type": "research_chat",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "research_chat_agent"


def test_chat_defaults_to_pre_trade_when_conversation_type_omitted():
    """Omitting conversation_type preserves the pre-Phase-71 pre_trade flow.

    Default routing -> agent0 profile, conversation_type response field
    surfaces as 'pre_trade' (backward-compat default).
    """
    resp = _post_chat({
        "message": "Should I take this trade?",
    })
    assert resp.status_code == 200, resp.data
    body = json.loads(resp.data)
    assert body["host_agent_id"] == "agent0"
    assert body["conversation_type"] == "pre_trade"
    # Internally, profile resolved to agent0 and conversation_type stayed None.
    assert resp._captured["profile_name"] == "agent0"  # type: ignore[attr-defined]
    assert resp._captured["conversation_type"] is None  # type: ignore[attr-defined]
