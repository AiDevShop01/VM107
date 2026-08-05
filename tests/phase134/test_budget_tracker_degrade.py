"""D-08 RED gate — MongoBudgetTracker ops must fast-fail + fall back + emit a health signal.

Phase 134 Wave 0 (Nyquist RED-first). The budget check runs on the per-LLM-call hot path
(`ExecutionBoundary.check` -> `get_daily_total`); a down Mongo must NEVER block or raise into
that path. This test points a `MongoBudgetTracker` at an unreachable host and asserts each op:

  (1) returns within a bounded budget (< serverSelectionTimeoutMS/1000 + margin),
  (2) yields an in-memory-fallback value instead of raising/blocking to the caller,
  (3) records `budget_mongo` unavailable in the shared SourceHealthRegistry.

MUST FAIL today (RED): `MongoClient(mongo_uri, retryWrites=True, w="majority")` is un-timed, so
the first op blocks on pymongo's ~30s default server-selection window, no in-memory fallback is
wired at the caller, and no degrade signal is emitted. Wave 1 (134-05, D-08) turns it green by
adding `serverSelectionTimeoutMS`, guarding the first op, falling back to InMemoryBudgetTracker,
and emitting `report("budget_mongo", available=False, ...)`.
"""
import os
import sys
import threading
import time

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pymongo.errors import PyMongoError  # noqa: E402

# Deliberately NO serverSelectionTimeoutMS in the URI — the timeout must come from the CODE
# (the fix), not the connection string, so today's un-timed client is provably RED.
UNREACHABLE_URI = "mongodb://127.0.0.1:1"
BOUND_SECONDS = 6.0        # 5000ms default fast-fail + ~1s margin
HARD_CAP_SECONDS = 8.0     # never wait the full ~30s un-timed block


def _run_bounded(fn, cap: float = HARD_CAP_SECONDS):
    """Run `fn` on a daemon thread; return (result_box, elapsed, still_running)."""
    box: dict = {"value": None, "exc": None}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — capture to assert on the degrade contract
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True)
    start = time.monotonic()
    t.start()
    t.join(cap)
    elapsed = time.monotonic() - start
    return box, elapsed, t.is_alive()


def _make_tracker():
    from core.boundary.budget_tracker import MongoBudgetTracker

    return MongoBudgetTracker(UNREACHABLE_URI)


def test_budget_tracker_down_mongo_bounded_fallback_and_signal():
    from emitters.source_health_registry import SourceHealthRegistry

    # Deterministic baseline for the health assertion.
    SourceHealthRegistry.get_shared_instance().clear()

    tracker = _make_tracker()
    failures: list[str] = []

    # (1)+(2) get_daily_total: bounded + in-memory-fallback value (no raise into the caller).
    box, elapsed, still_running = _run_bounded(tracker.get_daily_total)
    if still_running:
        failures.append(
            f"get_daily_total did not return within {HARD_CAP_SECONDS}s "
            f"(un-timed MongoClient blocks ~30s on server selection)"
        )
    else:
        if elapsed >= BOUND_SECONDS:
            failures.append(
                f"get_daily_total took {elapsed:.2f}s (>= {BOUND_SECONDS}s budget)"
            )
        if box["exc"] is not None:
            failures.append(
                f"get_daily_total raised {type(box['exc']).__name__} "
                f"instead of returning the in-memory fallback"
            )
        elif not isinstance(box["value"], (int, float)):
            failures.append(
                f"get_daily_total returned {box['value']!r}; expected an in-memory fallback float"
            )

    # add_spend: bounded + non-raising (degrades silently on the hot path).
    box2, elapsed2, still_running2 = _run_bounded(lambda: tracker.add_spend("agent-x", 0.01))
    if still_running2:
        failures.append(f"add_spend did not return within {HARD_CAP_SECONDS}s")
    elif elapsed2 >= BOUND_SECONDS:
        failures.append(f"add_spend took {elapsed2:.2f}s (>= {BOUND_SECONDS}s budget)")
    elif box2["exc"] is not None:
        failures.append(
            f"add_spend raised {type(box2['exc']).__name__} instead of degrading"
        )

    # (3) degrade signal recorded in the shared registry.
    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    if "budget_mongo" not in snap:
        failures.append(
            "SourceHealthRegistry has no 'budget_mongo' entry (no degrade signal emitted)"
        )
    elif snap["budget_mongo"].available is not False:
        failures.append("'budget_mongo' health is not marked unavailable")

    assert not failures, "D-08 RED:\n  " + "\n  ".join(failures)


class _SlowRaisingCollection:
    """Fake collection: each op simulates the ~serverSelectionTimeoutMS cost, then raises.

    Counts calls so the test can prove the WR-02 sticky latch routes the vast majority of
    ops to the in-memory fallback WITHOUT re-issuing the (expensive) Mongo op.
    """

    SINGLE_OP_COST_S = 0.3

    def __init__(self):
        self.calls = 0

    def _op(self):
        self.calls += 1
        time.sleep(self.SINGLE_OP_COST_S)
        raise PyMongoError("injected op-time mongo outage")

    def update_one(self, *_a, **_k):
        self._op()

    def find_one(self, *_a, **_k):
        self._op()


def test_budget_tracker_degrade_is_sticky_aggregate_bounded():
    """WR-02: a down Mongo must cost ~0 per op in steady state, not the full timeout each call.

    Loops N budget ops during an outage; only the FIRST op probes Mongo (paying the timeout),
    the sticky latch absorbs the rest in ~0 for the cooldown window. Proves D-08 holds in
    AGGREGATE across the hot path, not just for a single op.
    """
    from core.boundary.budget_tracker import MongoBudgetTracker
    from emitters.source_health_registry import SourceHealthRegistry

    SourceHealthRegistry.get_shared_instance().clear()
    tracker = MongoBudgetTracker(UNREACHABLE_URI)
    fake = _SlowRaisingCollection()
    tracker._collection = fake

    N = 20
    start = time.monotonic()
    for _ in range(N):
        tracker.add_spend("agent-x", 0.01)   # arms the latch on the first call
        tracker.get_daily_total()
        tracker.get_agent_spend("agent-x")
    elapsed = time.monotonic() - start

    failures: list[str] = []

    # The latch means exactly ONE op reaches Mongo; the other (3*N - 1) are absorbed.
    if fake.calls != 1:
        failures.append(
            f"expected exactly 1 Mongo probe across {3 * N} ops (sticky latch), got {fake.calls}"
        )

    # Aggregate wall-clock ~ one op's cost, NOT (3*N) x the per-op timeout.
    aggregate_bound = _SlowRaisingCollection.SINGLE_OP_COST_S * 3
    if elapsed >= aggregate_bound:
        failures.append(
            f"{3 * N} ops during outage took {elapsed:.2f}s (>= {aggregate_bound:.2f}s); "
            f"latch is not sticky (every op paid the Mongo cost)"
        )

    # In-memory fallback still tracks spend correctly during the outage.
    if tracker.get_agent_spend("agent-x") <= 0.0:
        failures.append("in-memory fallback did not accumulate add_spend during the outage")

    # Degrade signal recorded (sanitized reason).
    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    if "budget_mongo" not in snap or snap["budget_mongo"].available is not False:
        failures.append("'budget_mongo' not marked unavailable")
    elif snap["budget_mongo"].failure_reason != "PyMongoError":
        failures.append(
            f"failure_reason={snap['budget_mongo'].failure_reason!r}; expected sanitized 'PyMongoError'"
        )

    assert not failures, "WR-02 sticky-latch:\n  " + "\n  ".join(failures)
