"""Phase 155 D-04 — chat.py seam: conversation_type=="macro_ask" routes to the executor.

Asserts the process() seam: when ``conversation_type == "macro_ask"`` the handler dispatches to
the ``MacroAskExecutor`` branch (executor invoked; ``_call_coordinator_monologue`` NOT invoked),
while any other conversation_type (e.g. ``macro_chat``) keeps its existing monologue path.

Target (built in 155-04): the macro_ask branch inside ``api/v1/trades/ai/chat.py`` + the executor
at ``agents.macro_ask_executor.executor``. RED by import until then. Async tests are marked
``@pytest.mark.asyncio`` (pytest-asyncio strict).
"""
from __future__ import annotations

import pytest

# RED-on-target: the executor (and the chat branch that dispatches to it) do not exist until 155-04.
from agents.macro_ask_executor.executor import MacroAskExecutor


@pytest.mark.asyncio
async def test_macro_ask_routes_to_executor(monkeypatch):
    """conversation_type=='macro_ask' → executor branch fires; monologue path NOT taken."""
    import api.v1.trades.ai.chat as chat

    executor_calls: list = []
    monologue_calls: list = []

    async def _fake_monologue(*a, **k):
        monologue_calls.append((a, k))
        return ("monologue", {})

    def _fake_run(self, *a, **k):
        executor_calls.append((a, k))
        return {"answer": "macro_ask answer", "limitations": []}

    monkeypatch.setattr(chat, "_call_coordinator_monologue", _fake_monologue)
    monkeypatch.setattr(MacroAskExecutor, "run", _fake_run)

    handler = chat.TradeAiChat()
    await handler.process({"query": "why is inflation cooling?", "conversation_type": "macro_ask"}, None)

    assert executor_calls, "macro_ask must dispatch to the MacroAskExecutor branch"
    assert not monologue_calls, "_call_coordinator_monologue must NOT run on the macro_ask path"


@pytest.mark.asyncio
async def test_macro_chat_path_unchanged(monkeypatch):
    """A non-macro_ask conversation_type keeps the existing coordinator-monologue path."""
    import api.v1.trades.ai.chat as chat

    monologue_calls: list = []

    async def _fake_monologue(*a, **k):
        monologue_calls.append((a, k))
        return ("monologue", {})

    monkeypatch.setattr(chat, "_call_coordinator_monologue", _fake_monologue)

    handler = chat.TradeAiChat()
    await handler.process({"query": "tell me about macro", "conversation_type": "macro_chat"}, None)

    assert monologue_calls, "macro_chat must still use the coordinator-monologue path"
