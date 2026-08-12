"""Phase 139 P7 — P1 recall loop-stall regression (SC-1).

Guards (single-source `guarded_commits.GUARDED_COMMITS['test_p1_loop_stall']`):
  7e25765  — feat(133-02): class-singleton BGE adapter + off-loop embed.
  ac6e4dc  — feat(133-02): offload QdrantBackend query_points to a thread
             (`await asyncio.to_thread(lambda: self.client.query_points(**kw))`).
  78f7800  — feat(133-04): gather concurrent recall.

What this locks (the P1 event-loop invariant, D-08.3 analog):
  A heartbeat coroutine measures the running loop's `loop.time()` drift while N warm
  recalls run concurrently via `asyncio.gather`. The recall's network vector I/O
  (`client.query_points`) is OFF the event loop (ac6e4dc wraps it in
  `asyncio.to_thread`), so a blocking client call cannot stall the loop: max drift
  stays < 50 ms. Reverting ac6e4dc turns the offloaded `await to_thread(...)` back
  into a direct sync call on the loop → each blocking query stalls the heartbeat
  well past 50 ms → RED.

DIVERGENCE from the analog (`tests/integration/test_p1_recall_perf.py`, State-of-
the-Art "Deprecated for F5 reuse"): that harness is live-Qdrant / mock-forbidden /
container-run. The F5 lock MONKEYPATCHES the backend — an in-process fake client
whose `query_points` BLOCKS (`time.sleep`) is the injected fault (D-10: no live
Qdrant, no container, no shared dev service touched). The blocking is what a
sync-on-loop call would leak into the heartbeat; the offload is what this test proves.

Tier-2 note: `@pytest.mark.requires_deps` — the P1 fixes live in the memory/embedding
import graph (faiss/langchain via the memory package on the pinned deps), so this runs
under the Tier-2 venv (VM107/.venv, python3.12). The heavy import is DEFERRED into the
test body so host-clean collection under `-m "not requires_deps"` deselects it without
a ModuleNotFoundError (no top-level heavy import).
"""
from __future__ import annotations

import pytest

from tests.regression_p7.guarded_commits import GUARDED_COMMITS

# Blocking budget per query + concurrency: a sync-on-loop call would leak the full
# BLOCK_S into the heartbeat; the off-loop offload keeps drift far under the 50 ms bar.
_BLOCK_S = 0.08
_N_CONCURRENT = 10
_STALL_BAR_MS = 50.0


def test_guarded_commits_include_p1_shas():
    """The single-source map carries the P1 loop-stall shas (host-clean self-check)."""
    shas = GUARDED_COMMITS["test_p1_loop_stall"]
    for base in ("7e25765", "ac6e4dc", "78f7800"):
        assert base in shas, f"missing P1 guarded sha {base}"


@pytest.mark.requires_deps
def test_recall_does_not_stall_loop_under_concurrency():
    """N concurrent warm recalls with a BLOCKING query client keep loop drift < 50 ms
    — proving the query I/O is offloaded off the event loop (ac6e4dc). Reverting the
    offload makes the blocking call run sync-on-loop → drift >> 50 ms → RED."""
    import asyncio
    import time
    from types import SimpleNamespace

    from plugins._memory.backend.qdrant_backend import QdrantBackend

    class _FastEmbed:
        """Async embed that returns immediately — the ONLY blocking source is the
        query client, so the stall (if any) isolates the query offload (ac6e4dc)."""

        async def embed(self, texts=None, project_id=None, model=None, normalize=True, **kwargs):
            return SimpleNamespace(embeddings=[[0.1] * 768])

    class _BlockingClient:
        """query_points BLOCKS the calling thread. Off-loop (to_thread) this is a
        thread nap; sync-on-loop it freezes the heartbeat."""

        def query_points(self, **kwargs):
            time.sleep(_BLOCK_S)
            return SimpleNamespace(points=[])

    backend = QdrantBackend(
        client=_BlockingClient(),
        embedding_service=_FastEmbed(),
        collection_name="agent_memory",
        vector_size=768,
        vector_name="test_vector",  # non-None -> skips _ensure_collection on the fake client
        project_scoped=False,
    )

    async def _recall(i):
        ctx = SimpleNamespace(project_id=f"p{i}")
        return await backend.search(query=f"concurrent recall {i}", top_k=5, context=ctx)

    async def _run():
        loop = asyncio.get_running_loop()
        stalls: list[float] = []
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                t = loop.time()
                await asyncio.sleep(0.01)
                stalls.append(loop.time() - t - 0.01)

        hb = asyncio.create_task(heartbeat())
        results = await asyncio.gather(*[_recall(i) for i in range(_N_CONCURRENT)])
        stop.set()
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
        return results, (max(stalls) * 1000 if stalls else 0.0)

    results, worst_stall_ms = asyncio.run(_run())

    # Contract unchanged: each recall returns a (here empty) result list.
    assert all(r == [] for r in results), "search must still return its result list"
    assert worst_stall_ms < _STALL_BAR_MS, (
        f"event loop stalled {worst_stall_ms:.1f}ms under {_N_CONCURRENT} concurrent "
        f"recalls with a {int(_BLOCK_S * 1000)}ms blocking query client (want < "
        f"{_STALL_BAR_MS:.0f}ms) — the query I/O is NOT off-loop (ac6e4dc reverted?)"
    )
