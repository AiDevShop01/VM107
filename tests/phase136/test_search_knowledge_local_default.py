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
