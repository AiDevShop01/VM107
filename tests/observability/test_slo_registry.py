"""RED→GREEN unit tests for the SLORegistry percentile singleton (Phase 139-01 Task 3).

SLORegistry is the SC-2 capture primitive: a thread-safe module-singleton that
records per-path latency samples into a bounded deque and returns nearest-rank
p50/p95 on read. Mirrors ``emitters/source_health_registry.py`` in shape, with a
MANDATORY ``threading.Lock`` divergence (recall runs on ``helpers/defer.py``
EventLoopThreads while model-call hooks fire on the main uvicorn loop — the
134-09/135-06 singleton-race class).
"""
from __future__ import annotations

import threading

import pytest

from core.observability.slo_registry import SLORegistry


@pytest.fixture(autouse=True)
def _reset_slo():
    SLORegistry.get_shared_instance().clear()
    yield
    SLORegistry.get_shared_instance().clear()


def test_single_sample_p50_p95_equal_value():
    r = SLORegistry.get_shared_instance()
    r.record("recall", 12.5)
    s = r.snapshot()["recall"]
    assert s["count"] == 1
    assert s["p50"] == 12.5
    assert s["p95"] == 12.5


def test_nearest_rank_p50_p95_over_1_to_100():
    r = SLORegistry.get_shared_instance()
    for i in range(1, 101):
        r.record("recall", float(i))
    s = r.snapshot()["recall"]
    assert s["count"] == 100
    # nearest-rank (not interpolated): p50 index (100*50)//100-1 = 49 -> 50
    assert 45 <= s["p50"] <= 55
    # p95 index (100*95)//100-1 = 94 -> 95
    assert 90 <= s["p95"] <= 100


def test_nearest_rank_non_multiple_of_100_uses_ceiling():
    """Regression for WR-01: when n*pct is not a multiple of 100 the index must
    use ceiling (ceil(pct/100 * n) - 1), not floor. Floor understated p50/p95 —
    e.g. n=3 p50 returned the minimum (idx 0) instead of the median (idx 1).
    The n=1..100 test above can't catch this (100*pct is always a multiple).
    """
    # n=3 -> p50 = ceil(1.5)-1 = idx 1 (median); p95 = ceil(2.85)-1 = idx 2 (max)
    r = SLORegistry()
    for v in (10.0, 20.0, 30.0):
        r.record("recall", v)
    s = r.snapshot()["recall"]
    assert s["p50"] == 20.0, "p50 of [10,20,30] must be the median, not the minimum"
    assert s["p95"] == 30.0

    # n=2 -> p50 = ceil(1.0)-1 = idx 0; p95 = ceil(1.9)-1 = idx 1
    r2 = SLORegistry()
    for v in (5.0, 15.0):
        r2.record("recall", v)
    s2 = r2.snapshot()["recall"]
    assert s2["p50"] == 5.0
    assert s2["p95"] == 15.0

    # n=7 sorted 1..7 -> p50 = ceil(3.5)-1 = idx 3 -> 4.0; p95 = ceil(6.65)-1 = idx 6 -> 7.0
    r3 = SLORegistry()
    for v in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0):
        r3.record("recall", v)
    s3 = r3.snapshot()["recall"]
    assert s3["p50"] == 4.0
    assert s3["p95"] == 7.0


def test_bounded_deque_maxlen_1024():
    r = SLORegistry.get_shared_instance()
    for i in range(2000):
        r.record("tool_dispatch", float(i))
    assert r.snapshot()["tool_dispatch"]["count"] == 1024


def test_concurrent_writers_no_loss_no_exception():
    r = SLORegistry.get_shared_instance()
    n_threads, m_samples = 8, 500

    def _writer():
        for i in range(m_samples):
            r.record("model_call", float(i))

    threads = [threading.Thread(target=_writer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # N*M = 4000 > maxlen -> bounded to 1024, Lock guarantees no corruption
    assert r.snapshot()["model_call"]["count"] == 1024


def test_clear_empties_all_paths():
    r = SLORegistry.get_shared_instance()
    r.record("recall", 1.0)
    r.record("tool_dispatch", 2.0)
    r.clear()
    assert r.snapshot() == {}


def test_get_shared_instance_is_singleton():
    assert SLORegistry.get_shared_instance() is SLORegistry.get_shared_instance()
