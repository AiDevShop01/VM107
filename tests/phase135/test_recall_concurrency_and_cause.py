"""Phase 135 SC-2 gap-closure (plan 135-06) — real-concurrency + wrong-cause recall.

Plan 135-03 landed the D3 health-bus signal but keyed the qdrant report by the bare
string "qdrant". Under VM107's real concurrent-subagent + background-EventLoopThread
model, a second context's *successful* search clobbers a still-outstanding context's
*failed* report on the shared process-wide `SourceHealthRegistry` singleton — so the
recall extension reads a false-healthy bus and renders a false "No memories or solutions
found" during a genuine outage (SC-2 / CR-01 regression, sibling of 134-09).

This suite drives the REAL `search_similarity_threshold -> _qdrant_search -> _QdrantContext
-> QdrantBackend.search -> bus -> recall` coupling (WR-04: the 135-03 suite bypassed it) under
GENUINE concurrency (a worker thread with its own event loop + `asyncio.gather`) — NEVER a
hand-set ContextVar (`helpers/context.py`'s shared-mutable-dict is exactly the race the fix
must avoid, so the test must not depend on it).

  Test A — cross-context outage survives concurrency + a worker-thread hop (RED pre-fix:
    B's success clobbers the shared bare "qdrant"; A reads healthy -> plain empty).
  Test B — an embedding fault surfaces as "embedding", NOT "qdrant unreachable" (RED
    pre-fix: the single over-broad try reports "qdrant" for an embedding fault, WR-01).
  Test C — a composite-key miss for a real ctxid falls back to the bare record (C floor;
    GREEN both pre- and post-fix — locks the safety floor against future key divergence).
  Test D — a healthy-but-empty corpus still renders the exact plain empty heading.

No shared dependency container is touched (D-10): fault injection is in-process raise only.
T-135-01 no-leak: every assertion checks ABSENCE of host:port in model-visible content.
Requires `-s` (tty_session.py reconfigures stdin at import).
"""
from __future__ import annotations

import asyncio
import importlib
import re
import threading
from types import SimpleNamespace

import pytest

from emitters.source_health_registry import SourceHealthRegistry


# ---------------------------------------------------------------------------
# In-process stubs (no shared container touched — D-10)
# ---------------------------------------------------------------------------

class _FakeEmbed:
    """Minimal async EmbeddingService stub: returns one 768-dim vector."""

    async def embed(self, texts=None, project_id=None, model=None, normalize=True, **kwargs):
        return SimpleNamespace(embeddings=[[0.1] * 768])


class _RaisingEmbed:
    """embed() raises with a host:port-laden message to prove no leak (wrong-cause fault)."""

    async def embed(self, texts=None, project_id=None, model=None, normalize=True, **kwargs):
        raise RuntimeError("embedding backend 10.0.0.5:8080 down")


class _RaisingClient:
    """query_points raises with a host:port-laden message (qdrant outage)."""

    def query_points(self, **kwargs):
        raise ConnectionError("failed to connect to qdrant at 127.0.0.1:6333")


class _OkClient:
    """query_points returns an empty (but successful) result set."""

    def query_points(self, **kwargs):
        return SimpleNamespace(points=[])


class _FakeHistory:
    def output_text(self):
        return "prior conversation context that is comfortably longer than the query floor"


class _FakeAgent:
    """Recall test-double exposing `.context.id` (the reader reads `self.agent.context.id`)."""

    def __init__(self, ctxid):
        self.history = _FakeHistory()
        self.context = SimpleNamespace(id=ctxid)

    def read_prompt(self, *args, **kwargs):
        return ""


class _FakeLogItem:
    """Captures every log_item.update(**kwargs) call the recall surface makes."""

    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


def _headings(log_item):
    return [u["heading"] for u in log_item.updates if "heading" in u]


def _joined_content(log_item):
    return " ".join(str(u.get("content", "")) for u in log_item.updates)


# ---------------------------------------------------------------------------
# REAL search coupling — construct a real Memory wrapper + QdrantBackend and drive
# `search_similarity_threshold` (runs _qdrant_search -> _QdrantContext -> search -> bus).
# ---------------------------------------------------------------------------

async def _real_search_for_context(ctxid, *, client=None, embed=None):
    from plugins._memory.backend.qdrant_backend import QdrantBackend
    from plugins._memory.helpers.memory import Memory

    backend = QdrantBackend(
        client=client or _OkClient(),
        embedding_service=embed or _FakeEmbed(),
        collection_name="agent_memory",
        vector_size=768,
        vector_name="test_vector",  # non-None -> skips _ensure_collection() on the fake client
        project_scoped=False,
    )
    wrap = Memory(
        db=SimpleNamespace(),  # unused: search delegates to the qdrant backend
        memory_subdir="default",
        backend=backend,
        knowledge_backend=None,
    )
    # Stamp the wrapper's context id the way the fix will (Memory.get stamps context_id at
    # both return sites). Drives the SAME object-carried key path the production reader uses.
    wrap.context_id = ctxid
    return await wrap.search_similarity_threshold(
        query="hello world", limit=5, threshold=0.6, filter="area == 'main'"
    )


_RECALL_MODULE = (
    "plugins._memory.extensions.python.message_loop_prompts_after._50_recall_memories"
)


def _drive_reader_empty(monkeypatch, ctxid):
    """Drive `RecallMemories.search_memories()` to its empty-results branch for a context
    whose `_FakeAgent.context.id == ctxid`, reading whatever is on the bus. Returns the
    fake log_item so callers can assert the heading/content."""
    recall_mod = importlib.import_module(_RECALL_MODULE)

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
            return []  # empty corpus / empty result -> reach the ambiguous empty branch

    async def _fake_get(agent):
        return _FakeDB()

    monkeypatch.setattr(recall_mod.Memory, "get", _fake_get)

    ext = recall_mod.RecallMemories(agent=_FakeAgent(ctxid))
    log_item = _FakeLogItem()
    loop_data = SimpleNamespace(extras_persistent={}, user_message=None)

    asyncio.run(ext.search_memories(log_item=log_item, loop_data=loop_data))
    return log_item


async def _gather_context_b():
    """Run context B's REAL succeeding search, interleaved via asyncio.gather (genuine
    fan-out) so its healthy report is the LAST write to the shared bare bus."""
    return list(await asyncio.gather(_real_search_for_context("ctxB", client=_OkClient())))


# ---------------------------------------------------------------------------
# Test A — cross-context outage survives real concurrency + a worker-thread hop
# ---------------------------------------------------------------------------

def test_cross_context_outage_survives_concurrency_and_thread_hop(monkeypatch):
    """Context A's failed search (raising client) runs on a SEPARATE worker thread with its
    own event loop (mirrors the DeferredTask/EventLoopThread topology); context B's
    successful search then runs LAST via asyncio.gather on the main loop. After both,
    context A's recall must STILL render DEGRADED (qdrant) — B's concurrent success across
    the thread boundary must not clobber A's outage.

    Pre-fix (RED): both searches report the shared bare "qdrant"; B's success (last write)
    clobbers A's failure; A's reader reads bare "qdrant"=True and renders plain empty.
    Post-fix (GREEN): A reads its own object-carried key "qdrant:ctxA"=False, unaffected."""
    # --- A: failing search on a worker thread with its own event loop ---
    worker_loop = asyncio.new_event_loop()
    worker = threading.Thread(target=worker_loop.run_forever, daemon=True)
    worker.start()
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _real_search_for_context("ctxA", client=_RaisingClient()), worker_loop
        )
        a_result = fut.result(timeout=30)  # block until A's outage is reported to the bus
    finally:
        worker_loop.call_soon_threadsafe(worker_loop.stop)
        worker.join(timeout=5)

    assert a_result == [], "A's failed search must still return [] (no contract change)"

    # --- B: succeeding search LAST, interleaved via asyncio.gather on the main loop ---
    b_results = asyncio.run(_gather_context_b())
    assert b_results == [[]], "B's empty-but-successful search returns []"

    # --- read context A's recall empty branch on the MAIN thread ---
    log_item = _drive_reader_empty(monkeypatch, "ctxA")
    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    heading = headings[-1]
    content = _joined_content(log_item)

    assert "DEGRADED" in heading.upper(), (
        f"A's outage was clobbered by B's concurrent success — expected DEGRADED, got {heading!r}"
    )
    assert heading != "No memories or solutions found", (
        "a live qdrant outage in context A must NOT render as a genuinely-empty corpus"
    )
    assert "qdrant" in heading.lower() or "qdrant" in content.lower(), "must name the cause"
    assert "impaired" in content.lower(), "degraded content must say impaired, not empty"
    # T-135-01 no-leak.
    assert "127.0.0.1" not in content and "6333" not in content, f"host:port leaked: {content!r}"
    assert not re.search(r":\d{2,5}", content), f"port-like token leaked: {content!r}"


# ---------------------------------------------------------------------------
# Test B — an embedding fault names the embedding subsystem, not qdrant (WR-01)
# ---------------------------------------------------------------------------

def test_embedding_failure_not_labeled_qdrant(monkeypatch):
    """A search whose embedding service raises (query_points never reached) must surface an
    EMBEDDING degraded line — never mislabeled 'qdrant unreachable'.

    Pre-fix (RED): the single over-broad try catches the embedding fault and reports
    "qdrant" -> reader renders "qdrant unreachable" and never names embedding.
    Post-fix (GREEN): embed has its own try -> reports "embedding" -> reader names it."""
    result = asyncio.run(
        _real_search_for_context("ctxE", client=_OkClient(), embed=_RaisingEmbed())
    )
    assert result == [], "an embedding fault still returns [] (graceful degradation)"

    log_item = _drive_reader_empty(monkeypatch, "ctxE")
    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    heading = headings[-1]
    content = _joined_content(log_item)
    combined = (heading + " " + content).lower()

    assert heading != "No memories or solutions found", "an embedding fault must render DEGRADED"
    assert "qdrant unreachable" not in combined, (
        "an embedding fault must NOT be mislabeled as a qdrant outage (WR-01)"
    )
    assert "embedding" in combined, "the degraded line must name the real failing subsystem"
    # T-135-01 no-leak: the embedding fault's host:port must not reach model-visible content.
    assert "10.0.0.5" not in content and ":8080" not in content, f"host:port leaked: {content!r}"
    assert not re.search(r":\d{2,5}", content), f"port-like token leaked: {content!r}"


# ---------------------------------------------------------------------------
# Test C — a composite-key miss for a real ctxid falls back to the bare record (C floor)
# ---------------------------------------------------------------------------

def test_composite_miss_falls_back_to_bare_degraded(monkeypatch):
    """Only the bare "qdrant" record is present (available=False) and the reader's ctxid is
    a NON-EMPTY id with NO composite "qdrant:{id}" record. The reader must STILL render
    DEGRADED — falling back to the bare record. Locks the C safety floor so a future
    context-key divergence degrades to today's working single-context signal, never plain
    empty. GREEN both pre- and post-fix."""
    SourceHealthRegistry.get_shared_instance().report(
        "qdrant", available=False, failure_reason="ConnectionError"
    )

    log_item = _drive_reader_empty(monkeypatch, "ctx-with-no-composite-record")
    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    heading = headings[-1]

    assert "DEGRADED" in heading.upper(), (
        f"a composite miss for a real ctxid must fall back to the bare DEGRADED signal, got {heading!r}"
    )
    assert heading != "No memories or solutions found", (
        "the C safety floor must never silently drop a known outage to plain empty"
    )


# ---------------------------------------------------------------------------
# Test D — a healthy-but-empty corpus still renders the exact plain empty heading
# ---------------------------------------------------------------------------

def test_healthy_empty_still_plain_no_false_degrade(monkeypatch):
    """A successful (empty) search for a fresh context must leave the reader rendering the
    exact plain 'No memories or solutions found' — no false-DEGRADED on the per-context
    path. GREEN both pre- and post-fix."""
    result = asyncio.run(_real_search_for_context("ctxH", client=_OkClient()))
    assert result == [], "empty-but-successful search returns []"

    log_item = _drive_reader_empty(monkeypatch, "ctxH")
    headings = _headings(log_item)
    assert headings, "the empty branch must emit a heading"
    assert headings[-1] == "No memories or solutions found", (
        "a healthy but empty corpus must still render the normal empty text"
    )
