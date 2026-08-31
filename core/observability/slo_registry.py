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

import os
import threading
from collections import deque


# ---------------------------------------------------------------------------
# AZI-05 (Phase 154-05) — cross-process Prometheus export.
#
# The ``SLORegistry`` below is a PROCESS-LOCAL ring buffer: ``.record()`` only
# fires in the ``vm107`` agent process, so the separate telemetry-publisher
# process reads its OWN empty registry (``paths: {}``). To make p50/p95
# observable OUTSIDE this process we ALSO observe a ``prometheus_client``
# Histogram alongside every ``.record()`` call-site (the two ``*_model_call_after``
# extensions, ``core/agents/tool_dispatch.py``, ``plugins/_memory/helpers/memory.py``)
# — the histogram lives in the SAME process where the samples are produced and is
# exported over ``/metrics`` (``start_metrics_server`` below), which the deployed
# VM106 Prometheus scrapes.
#
# The import + every observe is GUARDED (T-154-14): a missing / broken
# ``prometheus_client`` degrades to record-only (the histogram becomes a no-op)
# and NEVER raises into the agent hot-path. The in-process ``SLORegistry`` stays
# the source of truth for ``/api/v1/telemetry/slo`` (SC-2) — this is purely the
# additive cross-process path.

# Canonical SLO path keys + their budgets (api/v1/telemetry/slo.py):
#   recall p95<300ms, tool_dispatch p95<100ms, model_call p95<30000ms.
_CANONICAL_SLO_PATHS = ("recall", "tool_dispatch", "model_call")

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        Histogram as _Histogram,
        start_http_server as _prom_start_http_server,
    )

    # Buckets in ms spanning all three budgets so p50/p95 land in a meaningful
    # bucket for each path (fast tool_dispatch through slow model_call).
    SLO_LATENCY_MS = _Histogram(
        "vm107_slo_latency_ms",
        "VM107 SLO path latency (ms), labelled by SLO path (AZI-05).",
        labelnames=["path"],
        buckets=(
            5, 10, 25, 50, 100, 250, 300, 500,
            1000, 2500, 5000, 10000, 30000, 60000,
        ),
    )
    # Pre-create the canonical label children so the metric family (carrying a
    # ``path=`` label) is present in ``/metrics`` from boot — a Prometheus scrape
    # sees the series even before the first sample, making the cross-process
    # assertion deterministic (not dependent on traffic timing).
    for _p in _CANONICAL_SLO_PATHS:
        SLO_LATENCY_MS.labels(path=_p)
    _PROM_AVAILABLE = True
except Exception:  # pragma: no cover — degraded path (missing/broken dep)
    SLO_LATENCY_MS = None
    _prom_start_http_server = None
    _PROM_AVAILABLE = False


def observe_slo_latency(path: str, elapsed_ms: float) -> None:
    """Observe one latency sample (ms) on the cross-process Prometheus histogram.

    GUARDED (T-154-14): a missing/broken ``prometheus_client`` or any observe
    error is swallowed — the record hot-path must never raise. Call ALONGSIDE
    ``SLORegistry.get_shared_instance().record(path, elapsed_ms)`` at each
    call-site; the in-process registry remains authoritative for the SC-2 endpoint.
    """
    if not _PROM_AVAILABLE or SLO_LATENCY_MS is None:
        return
    try:
        SLO_LATENCY_MS.labels(path=path).observe(elapsed_ms)
    except Exception:  # pragma: no cover — never break the agent loop
        pass


_metrics_server_started = False
_metrics_server_lock = threading.Lock()


def start_metrics_server(port: int = 9107) -> bool:
    """Start the ``prometheus_client`` ``/metrics`` HTTP server ONCE in this process.

    Idempotent + guarded: a double-start is a no-op; a missing ``prometheus_client``
    or a bind error (e.g. port already in use) degrades to no-metrics-endpoint and
    NEVER raises into the boot path. The port defaults to 9107 and can be overridden
    with ``VM107_METRICS_PORT``. Returns True if a server is (now) running.

    Bound inside the container to 0.0.0.0:9107; the HOST publish interface is what
    enforces the non-public posture (compose maps it to loopback/VM106-reachable
    only — T-154-12), not this in-container bind.
    """
    global _metrics_server_started
    if not _PROM_AVAILABLE or _prom_start_http_server is None:
        return False
    with _metrics_server_lock:
        if _metrics_server_started:
            return True
        try:
            resolved_port = int(os.environ.get("VM107_METRICS_PORT", port))
            _prom_start_http_server(resolved_port)
            _metrics_server_started = True
        except Exception:  # pragma: no cover — a bind failure must not brick boot
            return False
    return _metrics_server_started


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
