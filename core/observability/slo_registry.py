"""In-app p50/p95 SLO capture (Phase 139 / P7, SC-2, decision D-01).

A thread-safe module-singleton that records per-path latency samples into a
bounded ``collections.deque`` and returns nearest-rank p50/p95 on read. Mirrors
``emitters/source_health_registry.py``'s ``get_shared_instance()`` singleton
shape, with a MANDATORY ``threading.Lock`` divergence:

Recall runs on ``helpers/defer.py`` EventLoopThreads while the model-call hooks
fire on the main uvicorn loop — multiple threads write the same path's deque.
An unlocked deque can drop samples or read percentiles mid-mutation (the exact
134-09/135-06 SourceHealthRegistry-race defect class). Every ``record()`` append
and the snapshot copy in ``snapshot()`` are held under the lock; the O(n log n)
sort happens on the copied list OUTSIDE the lock so the hot-path critical section
stays O(1).

Percentiles are nearest-rank (not interpolated) on ≤1024 samples/path — no new
dependency (stdlib ``deque``/``threading`` only); a streaming estimator is
rejected at this volume (D-01a).

Canonical path keys used across the phase: "recall", "tool_dispatch", "model_call".
"""
from __future__ import annotations

import threading
from collections import deque


def _nearest_rank(sorted_xs: list[float], pct: int) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list.

    Index = max(0, ceil(pct/100 * n) - 1). The ceiling is computed with exact
    integer math as ``-(-(n*pct)//100)`` (floor of the negation, negated) and
    clamped to [0, n-1]. Floor division here would understate percentiles
    whenever ``n*pct`` is not an exact multiple of 100 (e.g. n=3, pct=50 must
    return the median at index 1, not the minimum at index 0).
    """
    n = len(sorted_xs)
    idx = -(-(n * pct) // 100) - 1
    if idx < 0:
        idx = 0
    elif idx >= n:
        idx = n - 1
    return sorted_xs[idx]


class SLORegistry:
    """Process-wide, thread-safe per-path latency percentile registry."""

    _shared_instance: "SLORegistry | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self, maxlen: int = 1024) -> None:
        self._maxlen = maxlen
        self._buf: dict[str, deque] = {}
        self._lock = threading.Lock()

    @classmethod
    def get_shared_instance(cls) -> "SLORegistry":
        """Process-wide singleton accessor.

        Tests that need an isolated registry should instantiate
        ``SLORegistry()`` directly and inject it.
        """
        if cls._shared_instance is None:
            with cls._singleton_lock:
                if cls._shared_instance is None:
                    cls._shared_instance = cls()
        return cls._shared_instance

    def record(self, path: str, elapsed_ms: float) -> None:
        """Thread-safe append of one latency sample (ms) for ``path``."""
        with self._lock:
            buf = self._buf.get(path)
            if buf is None:
                buf = deque(maxlen=self._maxlen)
                self._buf[path] = buf
            buf.append(elapsed_ms)

    def snapshot(self) -> dict[str, dict]:
        """Return ``{path: {count, p50, p95}}`` with nearest-rank percentiles.

        The per-path list copy is taken under the lock; sorting/percentile math
        runs on the copy outside the lock to keep the critical section O(1)/copy.
        """
        with self._lock:
            copied = {p: list(d) for p, d in self._buf.items()}
        out: dict[str, dict] = {}
        for path, xs in copied.items():
            if not xs:
                continue
            xs.sort()
            out[path] = {
                "count": len(xs),
                "p50": _nearest_rank(xs, 50),
                "p95": _nearest_rank(xs, 95),
            }
        return out

    def clear(self) -> None:
        """Reset all per-path buffers (used between tests / by the reset autouse)."""
        with self._lock:
            self._buf.clear()
