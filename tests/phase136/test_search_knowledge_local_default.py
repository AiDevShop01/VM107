"""SC-1 gate — search_knowledge defaults to LOCAL Qdrant; VM101 is fallback-only.

P4 / D-02 + D-03 (RED until 136-03 rewrites ``tools/search_knowledge.py``):

  1. local-default happy path returns corpus hits WITHOUT calling VM101 — the
     httpx path must not fire when local Qdrant is healthy.
  2. a genuine empty-but-successful local result stays empty and does NOT
     trigger the VM101 fallback (fallback fires on local ERROR, never on empty).
  3. a local Qdrant ERROR (reported ``available=False`` on the health bus)
     surfaces a typed DEGRADED signal AND (flag-on) attempts the VM101 fallback.
  4. the DEGRADED signal leaks NO host:port / IP — ``type(e).__name__`` only
     (T-135-01): none of ``127.0.0.1``, ``6333``, or any dotted-quad IP.

The tool import is guarded INSIDE the ``_run_tool`` helper so this file COLLECTS
at develop HEAD (where the tool is still VM101-HTTP-only); the tests then fail
RED on behaviour, not on import. The "VM101 not called" assertion is the
deterministic RED lever — at HEAD the tool has only the httpx path, so it always
calls VM101 regardless of whether the real VM101 host is up or down.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

_DOTTED_QUAD = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")


def _fake_agent(ctx_id: str = "phase136-ctx"):
    """Minimal agent the tool's execute() touches: context.id (135-06 key) + log."""
    context = SimpleNamespace(id=ctx_id, log=MagicMock())
    return SimpleNamespace(agent_name="phase136-test-agent", context=context)


class _RecordingHttpx:
    """Stand-in for the ``httpx`` module the tool imports — records VM101 calls.

    Lets the SC-1 gate assert the VM101 HTTP path was (not) taken without real
    network. Preserves ``.RequestError`` so the tool's ``except httpx.RequestError``
    still references a real exception type.
    """

    def __init__(self, results=None):
        import httpx as _real

        self.RequestError = _real.RequestError
        self.calls: list[dict] = []
        self._results = (
            results
            if results is not None
            else [{"text": "vm101 stub hit", "score": 0.9, "metadata": {}}]
        )

    def AsyncClient(self, *args, **kwargs):
        recorder = self.calls
        results = self._results

        class _Client:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *exc):
                return False

            async def post(self_inner, url, json=None, **kw):
                recorder.append({"url": url, "json": json})
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {"results": results},
                    text="",
                )

        return _Client()


def _run_tool(monkeypatch, query, agent=None, httpx_results=None):
    """Build ``SearchKnowledgeTool`` with a recording httpx, run ``execute(query=...)``.

    Returns ``(response, fake_httpx)`` so tests can assert on both the message and
    whether the VM101 HTTP path was taken. The tool import is deferred here (RED-safe).
    """
    from tools.search_knowledge import SearchKnowledgeTool  # guarded import
    import tools.search_knowledge as sk_mod

    fake_httpx = _RecordingHttpx(results=httpx_results)
    monkeypatch.setattr(sk_mod, "httpx", fake_httpx)

    tool = SearchKnowledgeTool(
        agent=agent or _fake_agent(),
        name="search_knowledge",
        method=None,
        args={},
        message="",
        loop_data=None,
    )
    response = asyncio.run(tool.execute(query=query))
    return response, fake_httpx


def test_local_default_returns_hits_without_calling_vm101(monkeypatch):
    """SC-1.1: healthy local Qdrant serves hits; the VM101 httpx path must NOT fire."""
    response, fake_httpx = _run_tool(monkeypatch, "what is liquidity")
    assert fake_httpx.calls == [], (
        "VM101 was called on the local-default happy path — search_knowledge must "
        "read local Qdrant first and only fall back to VM101 on a LOCAL ERROR (D-02). "
        f"Recorded VM101 calls: {fake_httpx.calls}"
    )
    assert "Error" not in (response.message or ""), response.message


def test_genuine_empty_does_not_trigger_vm101_fallback(monkeypatch):
    """SC-1.2: an empty-but-successful local result stays empty, no VM101 fallback."""
    _response, fake_httpx = _run_tool(
        monkeypatch, "zzz-nonexistent-corpus-token-zzz"
    )
    assert fake_httpx.calls == [], (
        "VM101 fallback fired on a genuine EMPTY result — fallback must gate on a "
        "local health-bus error, never on `not hits` (Pitfall 2 / D-02)."
    )


def test_local_error_surfaces_degraded_and_attempts_vm101(monkeypatch):
    """SC-1.3: a local Qdrant error -> typed DEGRADED signal + (flag-on) VM101 fallback."""
    from emitters.source_health_registry import SourceHealthRegistry

    agent = _fake_agent("phase136-degraded-ctx")
    ctxid = agent.context.id
    reg = SourceHealthRegistry.get_shared_instance()
    # Simulate the outage QdrantBackend.search would report from inside its except.
    reg.report("qdrant", available=False, failure_reason="ConnectionError")
    reg.report(f"qdrant:{ctxid}", available=False, failure_reason="ConnectionError")

    monkeypatch.setenv("SEARCH_KNOWLEDGE_VM101_FALLBACK", "1")
    response, fake_httpx = _run_tool(monkeypatch, "what is liquidity", agent=agent)

    msg = response.message or ""
    assert "DEGRADED" in msg.upper(), (
        "local Qdrant error must surface a typed DEGRADED signal (D-03), not a "
        f"silent/plain empty. Got: {msg!r}"
    )
    assert len(fake_httpx.calls) >= 1, (
        "flag-on VM101 fallback must be attempted when the local path ERRORS (D-02)."
    )


def test_degraded_signal_has_no_host_port_or_ip_leak(monkeypatch):
    """SC-1.4 / T-135-01: the DEGRADED signal names the failure CLASS only — no IP/port."""
    from emitters.source_health_registry import SourceHealthRegistry

    agent = _fake_agent("phase136-leak-ctx")
    ctxid = agent.context.id
    reg = SourceHealthRegistry.get_shared_instance()
    reg.report("qdrant", available=False, failure_reason="ConnectionError")
    reg.report(f"qdrant:{ctxid}", available=False, failure_reason="ConnectionError")

    # fallback OFF so the returned message is purely the local DEGRADED signal.
    monkeypatch.delenv("SEARCH_KNOWLEDGE_VM101_FALLBACK", raising=False)
    response, _fake_httpx = _run_tool(monkeypatch, "what is liquidity", agent=agent)

    msg = response.message or ""
    assert "DEGRADED" in msg.upper(), f"expected a DEGRADED signal, got: {msg!r}"
    assert "127.0.0.1" not in msg, msg
    assert "6333" not in msg, msg
    assert not _DOTTED_QUAD.search(msg), (
        f"DEGRADED signal leaked a dotted-quad IP (T-135-01 violation): {msg!r}"
    )


def _run_tool_with_local_hits(monkeypatch, query, agent, hits):
    """Run ``execute()`` with the LOCAL v2.search path forced to return ``hits``.

    Monkeypatches ``plugins._memory.helpers.memory`` so the tool's in-execute
    ``Memory.get(self.agent) -> db._get_knowledge_v2_backend().search(...)`` chain
    yields a genuine NON-EMPTY local result WITHOUT touching a real Qdrant. This is
    the missing coverage that lets a stale, failure-only ``embedding:{ctxid}=False``
    interact with a genuinely-successful local call (CR-01).
    """
    import plugins._memory.helpers.memory as mem_mod

    class _FakeV2Backend:
        async def search(self, query, top_k, context, area=None):  # QdrantBackend.search shape
            return list(hits)

    class _FakeDb:
        memory_subdir = "default"
        context_id = getattr(getattr(agent, "context", None), "id", "") or ""

        def _get_knowledge_v2_backend(self):
            return _FakeV2Backend()

    async def _fake_get(agent_arg):  # Memory.get is a staticmethod(agent) — bind-free
        return _FakeDb()

    monkeypatch.setattr(mem_mod.Memory, "get", staticmethod(_fake_get), raising=True)
    # Neutralise the real context constructor — the fake backend ignores context.
    monkeypatch.setattr(mem_mod, "_QdrantContext", lambda *a, **k: object(), raising=False)

    return _run_tool(monkeypatch, query, agent=agent)


def test_stale_embedding_health_does_not_discard_real_hits(monkeypatch):
    """CR-01 (RED at d518663): a stale ``embedding:{ctxid}=False`` health record must
    NOT discard a genuine NON-EMPTY local result behind a false DEGRADED.

    ``report("embedding", available=True)`` is never called (embedding health is
    failure-only and sticky until an emitter ``clear()``), so one transient
    embedding hiccup permanently taints a context. The tool must be hits-first:
    a non-empty local result is returned unconditionally and the health bus is
    consulted ONLY to explain a genuinely-empty result (mirroring
    ``_50_recall_memories.py``). RED before the fix: the tool reads the bus first
    and returns a false DEGRADED, discarding the real hit.
    """
    from emitters.source_health_registry import SourceHealthRegistry

    agent = _fake_agent("phase136-stale-embed-ctx")
    ctxid = agent.context.id
    real_hit_text = "liquidity is the depth available in the order book"

    # (2) Seed a STALE embedding=False for this ctxid (an earlier transient failure
    #     that was never re-marked healthy — the failure-only, sticky bus entry).
    SourceHealthRegistry.get_shared_instance().report(
        f"embedding:{ctxid}", available=False, failure_reason="RuntimeError"
    )

    # Fallback OFF so any DEGRADED comes PURELY from the (buggy) bus-first ordering.
    monkeypatch.delenv("SEARCH_KNOWLEDGE_VM101_FALLBACK", raising=False)

    # (1) Force the local path to return a genuine non-empty hit.
    response, fake_httpx = _run_tool_with_local_hits(
        monkeypatch,
        "what is liquidity",
        agent,
        hits=[{"text": real_hit_text, "score": 0.75}],
    )
    msg = response.message or ""

    # (3) The real hit must be returned; NO false DEGRADED.
    assert "DEGRADED" not in msg.upper(), (
        "CR-01: a stale embedding=False health record discarded a genuine non-empty "
        f"local result behind a false DEGRADED. Got: {msg!r}"
    )
    assert real_hit_text in msg, (
        f"expected the genuine local hit in the response, got: {msg!r}"
    )

    # (4) Non-empty local hits must NEVER trigger the VM101 fallback.
    assert fake_httpx.calls == [], (
        f"VM101 was called despite a non-empty local result: {fake_httpx.calls}"
    )
