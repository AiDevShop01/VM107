"""Phase 133 (P1) — D-08 event-loop & I/O performance verification harness.

Four committed acceptance checks for the recall/embedding refactor. They are
RED **by design** in Wave 0: they reference the process-singleton model
(``BgeEmbeddingAdapter._get_model`` classmethod + ``._load_count``, landed by
Plan 02) and the parallelized warm recall path (Plan 04). Running them now
fails/errors — Plans 02–05 turn them GREEN, Plan 06 records the "after".

Real Qdrant only (D-08 forbids mocks): every recall goes through a real
``QdrantBackend`` against the live ``knowledge_base_v2`` collection at
``os.environ["QDRANT_HOST"]`` (see conftest ``qdrant_test_client``).

Run (inside the recreated container):
    docker exec vm107-agent-zero python -m pytest tests/integration/test_p1_recall_perf.py -x
"""

import asyncio
import time

import pytest


def _import_backends():
    """Lazy sys.path-inject import (test_collection_separation.py:76-80 shape)."""
    import sys
    from pathlib import Path

    vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
    if str(vm107_path) not in sys.path:
        sys.path.insert(0, str(vm107_path))
    from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter
    from plugins._memory.backend.qdrant_backend import QdrantBackend

    return QdrantBackend, BgeEmbeddingAdapter


class _RecallContext:
    """Minimal AgentContext stand-in — kb_v2 is project_scoped=False so project_id is unused."""

    project_id = "phase133-perf-harness"
    memory_subdir = "phase133-perf-harness"
    task_id = "d08"


def _make_kb_v2_backend(client):
    """Build a real QdrantBackend over the shared knowledge_base_v2 corpus.

    Mirrors memory.py ``_get_knowledge_v2_backend`` construction: named vector
    ``general_embedding``, 768-dim, NOT project-scoped (global corpus).
    """
    QdrantBackend, BgeEmbeddingAdapter = _import_backends()
    return QdrantBackend(
        client=client,
        embedding_service=BgeEmbeddingAdapter(),
        collection_name="knowledge_base_v2",
        vector_size=768,
        vector_name="general_embedding",
        project_scoped=False,
    )


async def _recall(backend, query="market liquidity regime"):
    """One real warm recall against knowledge_base_v2."""
    return await backend.search(query=query, top_k=5, context=_RecallContext())


@pytest.mark.asyncio
@pytest.mark.slow
async def test_recall_p95_warm(warm_recall_stack, qdrant_test_client):
    """D-08.1 / SC-3: warm recall p95 < 300 ms (p50 reported).

    RED until the warm stack (Plan 02 singleton) exists — ``warm_recall_stack``
    errors during setup today, so this check cannot pass prematurely.
    """
    backend = _make_kb_v2_backend(qdrant_test_client)
    latencies = []
    for _ in range(50):  # warm loop of ~50 real recalls
        t = time.perf_counter()
        await _recall(backend)
        latencies.append(time.perf_counter() - t)
    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    print(f"[D-08.1] warm recall p50={p50 * 1000:.1f}ms  p95={p95 * 1000:.1f}ms  (n=50)")
    assert p95 < 0.300, f"warm recall p95 {p95 * 1000:.1f}ms exceeds 300ms bar"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_model_load_once(reset_load_count, qdrant_test_client):
    """D-08.2 / SC-2: SentenceTransformer loads exactly once across N recalls.

    Fire N=20 recalls with DISTINCT queries (force encode / cache-miss). The
    preload/first load counts as the one; subsequent recalls add zero. RED until
    Plan 02 lands ``_load_count`` (today it stays at the reset value 0).
    """
    BgeEmbeddingAdapter = reset_load_count
    backend = _make_kb_v2_backend(qdrant_test_client)
    for i in range(20):
        await _recall(backend, query=f"distinct query {i} macro liquidity regime shift")
    assert (
        BgeEmbeddingAdapter._load_count == 1
    ), f"SentenceTransformer loaded {BgeEmbeddingAdapter._load_count} times across 20 recalls (want exactly 1)"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_loop_stall_under_concurrency(warm_recall_stack, qdrant_test_client):
    """D-08.3 / SC-4: event-loop stall < 50 ms under 10 concurrent warm recalls.

    A heartbeat coroutine measures ``loop.time()`` drift while 10 recalls run via
    ``asyncio.gather``. If any I/O runs sync-on-loop the heartbeat stalls. RED
    until Plans 02/04 offload the sync calls to ``asyncio.to_thread``. Runs warm.
    """
    backend = _make_kb_v2_backend(qdrant_test_client)
    loop = asyncio.get_running_loop()
    stalls: list[float] = []
    stop = asyncio.Event()

    async def heartbeat():
        while not stop.is_set():
            t = loop.time()
            await asyncio.sleep(0.01)
            stalls.append(loop.time() - t - 0.01)

    hb = asyncio.create_task(heartbeat())
    await asyncio.gather(*[_recall(backend, query=f"concurrent recall {i}") for i in range(10)])
    stop.set()
    hb.cancel()
    try:
        await hb
    except asyncio.CancelledError:
        pass

    worst_stall_ms = max(stalls) * 1000 if stalls else 0.0
    print(f"[D-08.3] max loop stall under 10 concurrent recalls = {worst_stall_ms:.1f}ms")
    assert worst_stall_ms < 50, f"loop stalled {worst_stall_ms:.1f}ms under concurrency (want < 50ms)"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_kb_v2_recall_regression(qdrant_test_client):
    """D-08.4 / SC-4: knowledge_base_v2 hits still returned; v1 confirmed empty (A3).

    Regression bar for the recall refactor: querying a term present in
    ``knowledge_base_v2`` must still return hits (the shipped kb_v2 direct-recall
    behavior is non-negotiable). Also assert the raw ``knowledge_base`` (v1) point
    count is 0 — confirming v1 is genuinely empty BEFORE its fan-out drop is
    declared safe (RESEARCH assumption A3).

    Post-refactor the memory.py layer tags these hits ``area == "knowledge"``;
    this scaffold queries the backend directly, so v2_hits are the raw results.
    """
    backend = _make_kb_v2_backend(qdrant_test_client)
    v2_hits = await _recall(backend, query="trading strategy risk management")
    assert len(v2_hits) > 0, "knowledge_base_v2 returned no hits — kb_v2 recall regression"

    # A3 safety: v1 knowledge_base must be empty before it is dropped from fan-out.
    v1_count = qdrant_test_client.count(collection_name="knowledge_base").count
    assert v1_count == 0, f"knowledge_base (v1) is not empty ({v1_count} points) — A3 drop unsafe"
