"""Phase 155 post-review (CR-01 / WR-03) — event-loop-safe macro_ask executor offload.

The blind spot the whole existing phase155 suite shares: every macro_ask test either
monkeypatches ``MacroAskExecutor.run`` (test_chat_macro_ask_wiring) or calls the REAL
``run()`` from a SYNCHRONOUS test body (test_macro_ask_executor / test_macro_ask_e2e).
None of them drive the REAL ``run()`` through the handler while an event loop is already
running — exactly the production condition (``process()`` is an async coroutine awaited by
the async request path). Pre-fix, ``_handle_macro_ask`` called ``executor.run(...)``
DIRECTLY inside that coroutine; ``run()`` internally calls ``asyncio.run(self._fan_out(...))``
which raises ``RuntimeError: asyncio.run() cannot be called from a running event loop`` →
a bare HTTP 500 on EVERY real macro_ask request.

These tests lock the fix:
  * CR-01 — the REAL ``run()`` is driven through the handler inside an ACTIVE event loop and
    MUST NOT raise ``RuntimeError`` (proves the ``await asyncio.to_thread(...)`` offload).
  * WR-03 — when the executor raises internally, the handler returns a status="failure"
    honest envelope (not a propagated exception / bare 500), with the fail-loud semantics
    kept INSIDE the executor untouched.

Both drive the handler with ``request=None`` (journal_id resolves to "") — the request-less
accommodation already established in ``test_macro_chat_path_unchanged`` — so no Mongo/Flask
request context is needed and the envelope-persist branch is skipped.

nest_asyncio caveat (why CR-01 is asserted via the offload, not via ``pytest.raises``):
``helpers/runtime.py`` calls ``nest_asyncio.apply()`` at import, and importing ``chat`` pulls
that in. nest_asyncio monkeypatches ``asyncio.run`` to TOLERATE a nested call inside a running
loop, so the pre-fix direct ``executor.run(...)`` would NOT raise ``RuntimeError`` in-process
(it would instead re-enter and BLOCK the server's event loop for the whole fan-out — the real
defect, plus total fragility on any entrypoint that has not applied nest_asyncio). A
``pytest.raises(RuntimeError)`` guard would therefore be a tautology here. Instead we assert the
POSITIVE invariant the fix guarantees: ``run()`` executes on a WORKER thread with NO running
event loop (the ``asyncio.to_thread`` offload). That is RED against the pre-fix direct call
(which runs ``run()`` on the loop thread) regardless of nest_asyncio, and GREEN after.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from agents.macro_ask_executor.executor import MacroAskExecutor


@pytest.mark.asyncio
async def test_macro_ask_run_is_offloaded_off_the_event_loop(
    monkeypatch, stub_registry, stub_pillar_fetcher
):
    """CR-01: the REAL run() is offloaded to a worker thread (no running loop), not called inline.

    The pre-fix handler called the sync ``run()`` DIRECTLY inside the async coroutine, so
    ``run()`` executed on the event-loop thread while a loop was running — tripping
    ``asyncio.run() cannot be called from a running event loop`` on any entrypoint without
    nest_asyncio, and blocking the loop where nest_asyncio tolerates the re-entry. The fix
    (``await asyncio.to_thread(executor.run, ...)``) runs ``run()`` on a worker thread whose
    ``asyncio.run(self._fan_out(...))`` gets a clean private loop.

    We exercise the REAL ``run()`` (its genuine ``asyncio.run`` body executes via ``super().run``)
    and only OBSERVE the execution context — we do NOT stub the return value the way the existing
    wiring test does (which is exactly the blind spot that hid this bug).
    """
    import api.v1.trades.ai.chat as chat
    import agents.macro_ask_executor.executor as exec_mod

    main_thread = threading.current_thread()
    observed: dict = {}

    real_cls = exec_mod.MacroAskExecutor

    class _RecordingExecutor(real_cls):
        """Thin observation shim: records WHERE run() executes, then runs the REAL run()."""

        def run(self, **kwargs):  # noqa: D401 - delegates to the genuine implementation
            observed["thread"] = threading.current_thread()
            try:
                asyncio.get_running_loop()
                observed["loop_running_in_run_thread"] = True
            except RuntimeError:
                observed["loop_running_in_run_thread"] = False
            return super().run(**kwargs)  # the genuine asyncio.run(_fan_out(...)) path

    def _factory(*_a, **_k):
        return _RecordingExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())

    # The handler lazily does `from agents.macro_ask_executor.executor import MacroAskExecutor`
    # at call time, so patching the module attribute reroutes its `MacroAskExecutor()` call.
    monkeypatch.setattr(exec_mod, "MacroAskExecutor", _factory)

    handler = chat.TradeAiChat()

    resp = await handler._handle_macro_ask(
        {"query": "Why is inflation cooling while growth holds up?", "conversation_type": "macro_ask"},
        None,
        "macro_ask",
    )

    # (1) Offload proven — run() must NOT execute on the event-loop thread (RED pre-fix).
    assert observed.get("loop_running_in_run_thread") is False, (
        "executor.run() ran while an event loop was live in its thread — "
        "the sync asyncio.run() inside it either raises or blocks the loop (CR-01)"
    )
    assert observed.get("thread") is not None and observed["thread"] is not main_thread, (
        "executor.run() must be offloaded to a worker thread via asyncio.to_thread, "
        "not called inline on the event-loop thread"
    )

    # (2) The REAL fan-out/synthesize path still produced an honest, non-empty turn.
    payload = json.loads(resp.get_data(as_text=True))
    assert payload["status"] in {"success", "degraded"}, payload
    assert payload["response"], "the real fan-out/synthesize path must produce a non-empty answer"


@pytest.mark.asyncio
async def test_macro_ask_executor_raise_degrades_to_failure_envelope(monkeypatch):
    """WR-03: an executor raise is caught → honest status='failure' envelope, not a bare 500."""
    import api.v1.trades.ai.chat as chat
    import agents.macro_ask_executor.executor as exec_mod

    class _RaisingExecutor:
        def run(self, *, query, context, journal_id):  # noqa: ARG002 - signature match
            # Mirrors the executor's fail-loud path (e.g. empty-plan ValueError) reaching the handler.
            raise ValueError("no specialist matched this question")

    monkeypatch.setattr(exec_mod, "MacroAskExecutor", lambda *a, **k: _RaisingExecutor())

    handler = chat.TradeAiChat()

    resp = await handler._handle_macro_ask(
        {"query": "totally unroutable question", "conversation_type": "macro_ask"},
        None,
        "macro_ask",
    )

    payload = json.loads(resp.get_data(as_text=True))
    assert payload["status"] == "failure", payload
    assert payload["response"] == "", "a failed turn must never fabricate an answer"
    # The internal error is named honestly in limitations (WR-03 envelope contract).
    assert any("ValueError" in str(lim) for lim in payload["limitations"]), payload["limitations"]
