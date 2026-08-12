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
