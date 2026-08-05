"""Phase 135 D3 — Qdrant-outage-vs-empty-corpus signal (SC-2).

Two coupled halves ship together and this suite fails if EITHER ships alone
(Pitfall 2 / D3-02 is a REQUIRED completion of D3-01):

  Half A (D3-02, `qdrant_backend.search()`): a raised search freshens the
    process-wide `SourceHealthRegistry` bus to `available=False,
    failure_reason=type(e).__name__` (WR-04 / T-135-01 no host:port leak) and
    STILL returns `[]`; a successful search reports `available=True`.
    -> `test_search_freshens_bus_available_false_on_failure`
    -> `test_search_reports_bus_available_true_on_success`

  Half B (D3-01/03, recall extension empty branch): when the fresh bus says
    qdrant is down, the empty-results branch renders a DEGRADED heading naming
    the cause and instructing "impaired, not empty" instead of the plain
    "No memories or solutions found"; when qdrant is healthy it keeps the
    plain heading (normal empty-corpus semantics unchanged).
    -> `test_recall_empty_branch_degraded_when_bus_down`
    -> `test_recall_empty_branch_normal_when_bus_healthy`

Injected-fault only (D-10): no shared dependency container is touched — Half A
drives a real `QdrantBackend` with an in-process raising fake client; Half B
reports on the bus directly and stubs `Memory.get`.

Expected RED until Tasks 2-3 (the two source edits) land.
"""
from __future__ import annotations

import asyncio
import importlib
import re
from types import SimpleNamespace

import pytest

from emitters.source_health_registry import SourceHealthRegistry


# ---------------------------------------------------------------------------
# Half A — qdrant_backend.search() freshens the health bus (D3-02)
# ---------------------------------------------------------------------------

class _FakeEmbed:
    """Minimal async EmbeddingService stub: returns one 768-dim vector."""

    async def embed(self, texts=None, project_id=None, model=None, normalize=True, **kwargs):
        return SimpleNamespace(embeddings=[[0.1] * 768])


class _RaisingClient:
    """query_points raises with a host:port-laden message to prove no leak."""

    def query_points(self, **kwargs):
        raise ConnectionError("failed to connect to qdrant at 127.0.0.1:6333")


class _OkClient:
    """query_points returns an empty (but successful) result set."""

    def query_points(self, **kwargs):
        return SimpleNamespace(points=[])


def _run_search(client):
    from plugins._memory.backend.qdrant_backend import QdrantBackend

    backend = QdrantBackend(
        client=client,
        embedding_service=_FakeEmbed(),
        collection_name="agent_memory",
        vector_size=768,
        vector_name="test_vector",  # non-None -> skips _ensure_collection() on the fake client
        project_scoped=False,
    )
    ctx = SimpleNamespace(project_id="testproj")
    return asyncio.run(backend.search(query="hello world", top_k=5, context=ctx))


def test_search_freshens_bus_available_false_on_failure():
    """A raised search must report qdrant DOWN with a leak-free type-name reason,
    and STILL return [] (no return-contract change)."""
    result = _run_search(_RaisingClient())

    # Contract unchanged: graceful [] on failure.
    assert result == [], "search() must still return [] on failure (no contract change)"

    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    assert "qdrant" in snap, (
        "search()'s except block must freshen the health bus (D3-02); "
        f"snapshot keys={list(snap)}"
    )
    assert snap["qdrant"].available is False

    # WR-04 / T-135-01: failure_reason is the exception CLASS name, never str(e)/host:port.
    fr = snap["qdrant"].failure_reason or ""
    assert fr == "ConnectionError", (
        f"failure_reason must be type(e).__name__, got {fr!r} (str(e) would leak host:port)"
    )
    assert "127.0.0.1" not in fr and "6333" not in fr, f"host:port leaked into failure_reason: {fr!r}"
    assert not re.search(r":\d", fr), f"port-like token leaked into failure_reason: {fr!r}"


def test_search_reports_bus_available_true_on_success():
    """A successful (even empty-result) search must report qdrant HEALTHY."""
    result = _run_search(_OkClient())

    assert result == [], "empty-but-successful search returns []"

    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    assert "qdrant" in snap, "search()'s success path must report available=True (D3-02)"
    assert snap["qdrant"].available is True


# ---------------------------------------------------------------------------
# Half B — recall extension empty branch renders DEGRADED vs empty (D3-01/03)
# ---------------------------------------------------------------------------

_RECALL_MODULE = (
    "plugins._memory.extensions.python.message_loop_prompts_after._50_recall_memories"
)


class _FakeHistory:
    def output_text(self):
        return "prior conversation context that is comfortably longer than the query floor"


class _FakeAgent:
    def __init__(self):
        self.history = _FakeHistory()

    def read_prompt(self, *args, **kwargs):
        return ""


class _FakeLogItem:
    """Captures every log_item.update(**kwargs) call the recall surface makes."""

    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


def _drive_recall_empty(monkeypatch, *, qdrant_available):
    """Drive `RecallMemories.search_memories()` to its empty-results branch with the
    health bus pre-set. Returns the fake log_item so callers can assert the heading.

    `qdrant_available`: True/False report a qdrant entry on the bus; None leaves it absent.
    """
    recall_mod = importlib.import_module(_RECALL_MODULE)

    if qdrant_available is False:
        SourceHealthRegistry.get_shared_instance().report(
            "qdrant", available=False, failure_reason="ConnectionError"
        )
    elif qdrant_available is True:
        SourceHealthRegistry.get_shared_instance().report("qdrant", available=True)
    # None -> leave the bus with no qdrant entry (healthy/unknown)

    cfg = {
        "memory_recall_query_prep": False,  # skip the utility-model query-prep path
        "memory_recall_history_len": 1000,
        "memory_recall_memories_max_search": 10,
        "memory_recall_solutions_max_search": 8,
        "memory_recall_similarity_threshold": 0.6,
        "memory_recall_memories_max_result": 5,
        "memory_recall_solutions_max_result": 3,
        "memory_recall_post_filter": False,
    }
    monkeypatch.setattr(recall_mod.plugins, "get_plugin_config", lambda *a, **k: cfg)

    class _FakeDB:
        async def search_similarity_threshold(self, *args, **kwargs):
            return []  # empty corpus / empty result

    async def _fake_get(agent):
        return _FakeDB()

    monkeypatch.setattr(recall_mod.Memory, "get", _fake_get)

    ext = recall_mod.RecallMemories(agent=_FakeAgent())
    log_item = _FakeLogItem()
    loop_data = SimpleNamespace(extras_persistent={}, user_message=None)

    asyncio.run(ext.search_memories(log_item=log_item, loop_data=loop_data))
    return log_item


def _headings(log_item):
    return [u["heading"] for u in log_item.updates if "heading" in u]


def _joined_content(log_item):
    return " ".join(str(u.get("content", "")) for u in log_item.updates)


def test_recall_empty_branch_degraded_when_bus_down(monkeypatch):
    """Empty results + bus says qdrant down -> DEGRADED heading naming the cause,
    content instructing 'impaired, not empty', NO host:port leak."""
    log_item = _drive_recall_empty(monkeypatch, qdrant_available=False)

    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    heading = headings[-1]

    assert "DEGRADED" in heading.upper(), f"expected a DEGRADED heading, got {heading!r}"
    assert "qdrant" in heading.lower() or "qdrant" in _joined_content(log_item).lower(), (
        "degraded surface must name the cause (qdrant)"
    )
    assert heading != "No memories or solutions found", (
        "a qdrant outage must NOT render as a genuinely-empty corpus"
    )

    content = _joined_content(log_item)
    assert "impaired" in content.lower(), (
        "degraded content must instruct the agent recall is impaired, not empty"
    )
    # T-135-01 no-leak in the model-visible line.
    assert "127.0.0.1" not in content and "6333" not in content, f"host:port leaked: {content!r}"
    assert not re.search(r":\d{2,5}", content), f"port-like token leaked into content: {content!r}"


def test_recall_empty_branch_normal_when_bus_healthy(monkeypatch):
    """Empty results + qdrant healthy -> the plain empty heading is preserved."""
    log_item = _drive_recall_empty(monkeypatch, qdrant_available=True)

    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    assert headings[-1] == "No memories or solutions found", (
        "a healthy but empty corpus must still render the normal empty text"
    )


def test_recall_empty_branch_normal_when_bus_absent(monkeypatch):
    """Empty results + no qdrant bus entry at all -> plain empty heading (no false degrade)."""
    log_item = _drive_recall_empty(monkeypatch, qdrant_available=None)

    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    assert headings[-1] == "No memories or solutions found", (
        "absent bus entry must not be treated as degraded"
    )
