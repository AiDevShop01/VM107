"""Phase 139 P7 — P3-D3 degraded-CAUSE regression (SC-1) + recall SLO (SC-2).

Guards (single-source `guarded_commits.GUARDED_COMMITS['test_p3d3_degraded_cause']`):
  2a7ff89, 35e23ee, 514e4ca, e01bd54  — 135 D3 (freshen bus in search, render
                                         DEGRADED, context-scope the health key)
  0816788                             — this phase's cause-carrying init report
                                         (D-04, memory.py) + reader classification
                                         (D-05, _50_recall_memories.py).

Three halves + an SLO check (D-10 injected-fault ONLY — never halts or touches the
shared dev Qdrant; every fault is an in-process raise / monkeypatch):

  Half A (host-clean): the real `QdrantBackend.search` driven with an in-process
    raising fake client whose `query_points` raises a NameError (the 2026-08-12
    `qdrant_host` class of bug). The health bus must carry
    `failure_reason == type(e).__name__` ("NameError", code-class) and search must
    STILL return [] (no contract change). Proves the cause CLASS reaches the bus.

  Half B (requires_deps): the ACTUAL recall reader classifies the EXISTING
    `failure_reason` — code-class → "internal error", connect-class → "vector store
    unreachable", no down-record → plain "No memories or solutions found" — with NO
    host:port leak (T-135-01) and the hits-first read discipline preserved
    (135 CR-01: the bus is read only inside `if not memories and not solutions:`). D-05.

  Half C (requires_deps): the ACTUAL `Memory.get()` init path with
    `create_qdrant_client` monkeypatched to raise NameError reports a code-class
    cause to the bus (bare "qdrant" + context-scoped "qdrant:{ctxid}"). D-04 — this
    drives the REAL knowledge_base init path, closing the coverage gap that let the
    2026-08-12 NameError render as "no memories" (the 135 gates only counted
    construction sites + drove `episodic_memory_service`).

  SLO (requires_deps): a real `Memory.search_similarity_threshold` call records a
    sample into `SLORegistry('recall')` (SC-2), covering the FAISS branch.

Tier-2 note: Half B/C/SLO import the `agent`/`models`/`memory` chain, which uses
Python 3.12 syntax (PEP 695 `type` aliases in `helpers/subagents.py`) and heavy deps
(faiss/langchain/litellm). They run only under the Tier-2 venv (`VM107/.venv`,
python3.12) and are marked `@pytest.mark.requires_deps`; the host-clean fast loop
(`-m "not requires_deps"`) runs Half A only. Heavy imports are DEFERRED into the test
bodies so host-clean collection never hits the 3.12-syntax/ModuleNotFound wall.
"""
from __future__ import annotations

import asyncio
import importlib
import re
from types import SimpleNamespace

import pytest

from emitters.source_health_registry import SourceHealthRegistry
from core.observability.slo_registry import SLORegistry
from tests.regression_p7.guarded_commits import GUARDED_COMMITS

_RECALL_MODULE = (
    "plugins._memory.extensions.python.message_loop_prompts_after._50_recall_memories"
)
_MEMORY_MODULE = "plugins._memory.helpers.memory"
_FACTORY_MODULE = "plugins._memory.backend.factory"


# ---------------------------------------------------------------------------
# Half A — QdrantBackend.search() carries the cause CLASS to the bus (host-clean)
# ---------------------------------------------------------------------------

class _FakeEmbed:
    """Minimal async EmbeddingService stub: returns one 768-dim vector."""

    async def embed(self, texts=None, project_id=None, model=None, normalize=True, **kwargs):
        return SimpleNamespace(embeddings=[[0.1] * 768])


class _NameErrorClient:
    """query_points raises a NameError with a host:port-laden message.

    Mirrors the 2026-08-12 `qdrant_host` NameError: a CODE bug (not a connect
    failure) that a broad `except` previously masked as "vector store unreachable".
    The host:port in the message proves the no-leak discipline (only
    type(e).__name__ reaches the bus).
    """

    def query_points(self, **kwargs):
        raise NameError("name 'qdrant_host' is not defined at 127.0.0.1:6333")


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


def test_half_a_search_carries_code_class_cause():
    """A code-class (NameError) failure in search reaches the bus as the CLASS name,
    leak-free, and search still returns [] (contract unchanged)."""
    pytest.importorskip("qdrant_client")
    result = _run_search(_NameErrorClient())

    assert result == [], "search() must still return [] on failure (no contract change)"

    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    assert "qdrant" in snap, f"search()'s except must freshen the bus (D3-02); keys={list(snap)}"
    assert snap["qdrant"].available is False

    fr = snap["qdrant"].failure_reason or ""
    assert fr == "NameError", (
        f"failure_reason must be type(e).__name__ (code-class), got {fr!r}"
    )
    # T-135-01: the code-only cause never carries the host:port from the message.
    assert "127.0.0.1" not in fr and "6333" not in fr, f"host:port leaked into failure_reason: {fr!r}"
    assert not re.search(r":\d{2,5}", fr), f"port-like token leaked into failure_reason: {fr!r}"


# ---------------------------------------------------------------------------
# Half B — the recall reader classifies the cause (requires_deps)
# ---------------------------------------------------------------------------

class _FakeHistory:
    def output_text(self):
        return "prior conversation context that is comfortably longer than the query floor"


class _FakeAgent:
    def __init__(self, ctxid: str | None = None):
        self.history = _FakeHistory()
        self.context = SimpleNamespace(id=ctxid) if ctxid is not None else None

    def read_prompt(self, *args, **kwargs):
        return ""


class _FakeLogItem:
    """Captures every log_item.update(**kwargs) the recall surface makes."""

    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


def _headings(log_item):
    return [u["heading"] for u in log_item.updates if "heading" in u]


def _joined_content(log_item):
    return " ".join(str(u.get("content", "")) for u in log_item.updates)


def _drive_recall_empty(monkeypatch, *, failure_reason):
    """Drive the real `RecallMemories.search_memories()` to its empty-results branch
    with the health bus pre-seeded to a down record carrying `failure_reason`
    (None -> leave the bus with no qdrant entry). Returns the fake log_item."""
    recall_mod = importlib.import_module(_RECALL_MODULE)

    if failure_reason is not None:
        SourceHealthRegistry.get_shared_instance().report(
            "qdrant", available=False, failure_reason=failure_reason
        )
    # None -> no qdrant entry (genuinely-empty corpus / unknown health)

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


@pytest.mark.requires_deps
def test_half_b_code_class_renders_internal_error(monkeypatch):
    """A code-class down-record (NameError) renders 'internal error', not the
    misleading 'unreachable' — the honest surfacing of the 1bd9c98 class of bug."""
    log_item = _drive_recall_empty(monkeypatch, failure_reason="NameError")

    heading = _headings(log_item)[-1]
    content = _joined_content(log_item)
    assert "DEGRADED" in heading.upper(), f"expected DEGRADED heading, got {heading!r}"
    assert "internal error" in (heading + " " + content).lower(), (
        f"code-class cause must render 'internal error', got heading={heading!r}"
    )
    assert "unreachable" not in (heading + " " + content).lower(), (
        "a code bug must NOT be mislabelled as 'unreachable'"
    )
    assert heading != "No memories or solutions found"
    assert "impaired" in content.lower()
    # T-135-01 no host:port leak in the model-visible line.
    assert not re.search(r":\d{2,5}", content), f"port-like token leaked into content: {content!r}"


@pytest.mark.requires_deps
def test_half_b_connect_class_renders_unreachable(monkeypatch):
    """A connect-class down-record (ConnectionError) renders 'vector store
    unreachable' (still DEGRADED, still names qdrant)."""
    log_item = _drive_recall_empty(monkeypatch, failure_reason="ConnectionError")

    heading = _headings(log_item)[-1]
    content = _joined_content(log_item)
    assert "DEGRADED" in heading.upper()
    assert "vector store unreachable" in (heading + " " + content).lower(), (
        f"connect-class cause must render 'vector store unreachable', got heading={heading!r}"
    )
    assert heading != "No memories or solutions found"
    assert "impaired" in content.lower()
    assert not re.search(r":\d{2,5}", content), f"port-like token leaked into content: {content!r}"


@pytest.mark.requires_deps
def test_half_b_no_down_record_renders_plain_empty(monkeypatch):
    """No qdrant down-record -> the normal empty-corpus text is preserved (no false
    degrade). Also proves the read is hits-first: an absent bus never fabricates one."""
    log_item = _drive_recall_empty(monkeypatch, failure_reason=None)

    heading = _headings(log_item)[-1]
    assert heading == "No memories or solutions found", (
        f"absent down-record must render plain-empty, got {heading!r}"
    )


# ---------------------------------------------------------------------------
# Half C — the ACTUAL Memory.get() init path reports the code-class cause (D-04)
# ---------------------------------------------------------------------------

@pytest.mark.requires_deps
def test_half_c_actual_memory_get_reports_code_class_cause(monkeypatch):
    """Drive the REAL Memory.get() qdrant-init path with create_qdrant_client raising
    NameError -> the health bus gets a code-class cause on both the bare and the
    context-scoped key, and get() still falls back (no raise). This is the D-04
    requirement: the actual knowledge_base init path, not a proxy call site."""
    memory_mod = importlib.import_module(_MEMORY_MODULE)
    factory_mod = importlib.import_module(_FACTORY_MODULE)
    Memory = memory_mod.Memory

    # Fresh class state (process-wide dicts) so get() takes the init branch.
    Memory.index.clear()
    Memory.backends.clear()
    Memory.knowledge_backends.clear()
    Memory._redis_cache = None

    ctxid = "ctx-half-c"

    # --- make every pre-qdrant step in the try-block cheap ---
    monkeypatch.setattr(memory_mod, "get_agent_memory_subdir", lambda agent: "default")
    monkeypatch.setattr(
        memory_mod, "get_knowledge_subdirs_by_memory_subdir", lambda *a, **k: []
    )
    monkeypatch.setattr(memory_mod.plugins, "get_plugin_config", lambda *a, **k: {"memory_backend": "qdrant"})
    monkeypatch.setattr(
        Memory,
        "_get_embedding_config",
        staticmethod(lambda agent=None: SimpleNamespace(provider="p", name="n", build_kwargs=lambda: {})),
    )
    monkeypatch.setattr(memory_mod.models, "get_embedding_model", lambda *a, **k: object())
    monkeypatch.setattr(
        memory_mod.CacheBackedEmbeddings, "from_bytes_store", staticmethod(lambda *a, **k: object())
    )
    monkeypatch.setattr(memory_mod, "_get_redis_cache", lambda *a, **k: None)
    # Skip the FAISS index build after the fallback so the test stays light.
    monkeypatch.setattr(Memory, "initialize", staticmethod(lambda *a, **k: (object(), False)))

    # --- inject the 2026-08-12 class of fault at the qdrant client construction ---
    def _raise_nameerror(*a, **k):
        raise NameError("name 'qdrant_host' is not defined")

    monkeypatch.setattr(factory_mod, "create_qdrant_client", _raise_nameerror)

    agent = SimpleNamespace(
        context=SimpleNamespace(id=ctxid, log=SimpleNamespace(log=lambda **k: _FakeLogItem())),
        config=SimpleNamespace(knowledge_subdirs=[]),
    )

    wrap = asyncio.run(Memory.get(agent))
    # Fallback preserved: get() returns a wrapper with no qdrant backend (FAISS path).
    assert wrap is not None
    assert getattr(wrap, "backend", None) is None

    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    assert "qdrant" in snap, f"D-04: init failure must report to the bus; keys={list(snap)}"
    assert snap["qdrant"].available is False
    assert snap["qdrant"].failure_reason == "NameError", (
        f"D-04 must carry the code CLASS, got {snap['qdrant'].failure_reason!r}"
    )
    # Context-scoped report too (135-06 per-context key).
    assert f"qdrant:{ctxid}" in snap, "D-04 must also report the context-scoped key"
    assert snap[f"qdrant:{ctxid}"].failure_reason == "NameError"


# ---------------------------------------------------------------------------
# SLO — a real recall call records SLORegistry('recall') (SC-2)
# ---------------------------------------------------------------------------

@pytest.mark.requires_deps
def test_recall_call_records_recall_slo():
    """The additive SC-2 seam records a 'recall' sample around the real
    Memory.search_similarity_threshold (FAISS branch), without changing its return."""
    memory_mod = importlib.import_module(_MEMORY_MODULE)
    Memory = memory_mod.Memory

    class _FakeDB:
        async def asearch(self, *args, **kwargs):
            return []

    fake_self = SimpleNamespace(backend=None, db=_FakeDB())
    result = asyncio.run(
        Memory.search_similarity_threshold(fake_self, query="q", limit=1, threshold=0.5)
    )
    assert result == [], "recall return value must be unchanged by the timing wrap"

    snap = SLORegistry.get_shared_instance().snapshot()
    assert "recall" in snap, f"SC-2: recall latency must be recorded; keys={list(snap)}"
    assert snap["recall"]["count"] >= 1


# ---------------------------------------------------------------------------
# Guarded-commit annotation self-check
# ---------------------------------------------------------------------------

def test_guarded_commits_include_new_d04_d05_sha():
    """The single-source map must carry BOTH the 135 D3 shas AND this phase's new
    D-04/D-05 cause-carrying commit, so the revert harness (Plan 05) has a real RED
    to turn for the new fix."""
    shas = GUARDED_COMMITS["test_p3d3_degraded_cause"]
    for base in ("2a7ff89", "35e23ee", "514e4ca", "e01bd54"):
        assert base in shas, f"missing 135 D3 guarded sha {base}"
    # The new D-04/D-05 sha is appended by Plan 02 after the source commit lands.
    assert len(shas) >= 5, (
        "the new D-04/D-05 commit sha must be appended to test_p3d3_degraded_cause "
        f"(have {shas})"
    )
