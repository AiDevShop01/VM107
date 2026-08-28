"""Phase 169-04 (D-09 / G5 / AGV-11) — work_key single-flight dedup tests.

Proves the cross-process single-flight key holds the two properties the async fan-out needs:

1. **Dedup** — two calls with the SAME framework+output-shape tuple → the SAME key, so
   concurrent identical requests collapse to one compute.
2. **Replay-vs-live + output-shape separation** — a different knowledge_time OR detail_level
   OR horizon (OR narrative_mode / task / scope) → a DISTINCT key, so a PIT-replay and a
   live compute, and two different requested output shapes, never share a lock/result.

And that `acquire_single_flight` uses Redis `SET key val NX EX ttl` and degrades to
*proceed-without-lock* (returns True, never raises) when Redis is unavailable (T-169-04-02).

Hermetic: the pure `compute_work_key` is asserted directly; the SET NX behaviour is asserted
against fakes (a first-acquire-wins fake and an always-raising fake) — no live Redis.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.persistence.assessment_cache import acquire_single_flight, compute_work_key

_KT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _wk(**overrides) -> str:
    kwargs = dict(
        agent_type="domain_analyst",
        domain="inflation",
        geography="US",
        sector=None,
        state_version="v128",
        knowledge_time=_KT,
        detail_level="standard",
        horizon="NOWCAST",
        narrative_mode="analytical",
        task="assess",
    )
    kwargs.update(overrides)
    return compute_work_key(**kwargs)


# ---------------------------------------------------------------------------
# compute_work_key — dedup + separation
# ---------------------------------------------------------------------------


def test_work_key_is_idempotent_for_identical_tuple():
    assert _wk() == _wk()


def test_work_key_has_wk_prefix_and_sha256_shape():
    k = _wk()
    assert k.startswith("wk_")
    assert len(k) == 3 + 64
    assert all(c in "0123456789abcdef" for c in k[3:])


def test_work_key_distinct_across_detail_level():
    """A different requested detail_level → a distinct key (output-shape separation)."""
    assert _wk(detail_level="standard") != _wk(detail_level="deep")


def test_work_key_distinct_across_horizon():
    assert _wk(horizon="NOWCAST") != _wk(horizon="NEAR_TERM")


def test_work_key_distinct_across_knowledge_time_replay_vs_live():
    """Replay (past knowledge_time) and live (later) must NOT share a key."""
    replay = _wk(knowledge_time=_KT)
    live = _wk(knowledge_time=_KT + timedelta(days=1))
    assert replay != live


def test_work_key_distinct_across_narrative_mode_and_task():
    assert _wk(narrative_mode="analytical") != _wk(narrative_mode="briefing")
    assert _wk(task="assess") != _wk(task="explain")


def test_work_key_distinct_across_sector_scope():
    assert _wk(sector=None) != _wk(sector="energy")


def test_work_key_normalises_naive_and_aware_same_instant():
    naive = datetime(2026, 8, 28, 12, 0)
    assert _wk(knowledge_time=naive) == _wk(knowledge_time=_KT)


# ---------------------------------------------------------------------------
# acquire_single_flight — SET NX EX + graceful degrade
# ---------------------------------------------------------------------------


class _FakeRedisNX:
    """A minimal fake honouring SET ... NX (first caller wins, later callers get None)."""

    def __init__(self):
        self.held: set[str] = set()
        self.calls: list[dict] = []

    def set(self, key, value, nx=False, ex=None):
        self.calls.append({"key": key, "value": value, "nx": nx, "ex": ex})
        if nx and key in self.held:
            return None
        self.held.add(key)
        return True


class _RaisingRedis:
    def set(self, *args, **kwargs):
        raise ConnectionError("Connection refused")


def test_acquire_single_flight_first_caller_wins():
    redis = _FakeRedisNX()
    wk = _wk()
    assert acquire_single_flight(redis, wk, ttl=30) is True
    # Second concurrent caller for the same key is held off.
    assert acquire_single_flight(redis, wk, ttl=30) is False


def test_acquire_single_flight_issues_set_nx_ex():
    redis = _FakeRedisNX()
    acquire_single_flight(redis, _wk(), ttl=45)
    call = redis.calls[-1]
    assert call["nx"] is True
    assert call["ex"] == 45
    assert call["key"].startswith("wk_") or "wk_" in call["key"]


def test_acquire_single_flight_degrades_without_redis():
    """Redis unavailable → proceed-without-lock (returns True), never raises."""
    assert acquire_single_flight(_RaisingRedis(), _wk(), ttl=30) is True


def test_acquire_single_flight_degrades_when_redis_is_none():
    """A None client (unwired Redis) also degrades to proceed-without-lock."""
    assert acquire_single_flight(None, _wk(), ttl=30) is True
