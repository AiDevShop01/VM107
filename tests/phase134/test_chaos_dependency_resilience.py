"""SC-2 chaos gate — each dependency down → bounded call + deterministic fallback + health signal.

Phase 134 Wave 0 (Nyquist RED-first). This is the executable acceptance for SC-2 / D-10: with a
dependency redirected to an unreachable target (`127.0.0.1:1`, via the `*_down` conftest fixtures —
NEVER a docker-stop of the shared dev stack), the guarded path must, per dependency:

  (1) return/raise within its configured timeout budget (measure wall-clock < budget),
  (2) degrade gracefully — EITHER complete the turn on a deterministic fallback (in-memory budget /
      DLQ / empty-safe, no raise: mongo/vm100) OR fast-fail within budget AFTER emitting the degrade
      signal (bounded, OBSERVED propagate: postgres/qdrant). An unbounded hang or an UNOBSERVED raise
      (raise with no signal) is NOT resilient,
  (3) emit `_health.report(<dep>, available=False, …)` — asserted via
      `SourceHealthRegistry.get_shared_instance().snapshot()`.

Post-Wave-1 GREEN contract (per dep):
  - Mongo (budget_tracker): serverSelectionTimeoutMS-bounded → InMemoryBudgetTracker fallback +
    `budget_mongo` signal (swallow-fallback idiom).
  - Postgres (belief_store): connect_timeout-bounded → fail-fast re-raise + `postgres` signal
    (propagate idiom — no fake-empty beliefs).
  - Qdrant (memory factory): timeout-bounded liveness probe → fail-fast re-raise + `qdrant` signal
    (propagate idiom; the factory probe makes the down host observable, not a broken lazy backend).
  - VM100 (phase91 POST): (connect,read)-timeout-bounded → DLQ fallback + `phase91_uae` signal.

The Wave 2 phase gate runs this against all deps + the LLM path in the recreated container.
"""
import os
import sys
import threading
import time

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _run_bounded(fn, cap: float):
    """Run `fn` on a daemon thread; return (box, elapsed, still_running).

    Bounds the wall-clock so an un-timed hang cannot stall the suite for the full ~30s block.
    """
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


# ── Per-dependency drivers (exercise the guarded path the fixture has redirected) ──────────────

def _drive_mongo():
    from core.boundary.budget_tracker import MongoBudgetTracker

    # URI is irrelevant — the `mongo_down` fixture redirects MongoClient to 127.0.0.1:1.
    tracker = MongoBudgetTracker("mongodb://chaos-redirected")
    return tracker.get_daily_total()


def _drive_postgres():
    from core.belief.belief_store import BeliefStore

    # psycopg2.connect is redirected to 127.0.0.1:1 by the `postgres_down` fixture; the guarded
    # connect happens inside __init__ before any query.
    store = BeliefStore(
        postgres_url="postgresql://chaos-redirected/beliefs",
        mongo_url="mongodb://chaos-redirected/beliefs",
    )
    return store.query(subject_type="indicator", subject_id="CPIAUCSL")


def _drive_qdrant():
    from plugins._memory.backend.factory import create_backend

    # Exercise the FinGPT-GUARDED qdrant path (the memory factory), not a raw client:
    # a raw client can carry no health signal. The `qdrant_down` fixture redirects
    # QdrantClient to 127.0.0.1:1, so the factory's bounded liveness probe fast-fails
    # WITHIN the client timeout and emits the `qdrant` degrade signal (SC-2). The
    # embedding_service need only be non-None (it is not invoked on the down path).
    return create_backend(
        {"memory_backend": "qdrant", "qdrant_host": "192.168.1.151", "qdrant_port": 6333},
        embedding_service=object(),
    )


def _drive_vm100():
    from core.alerts.phase91_emit import emit_alert_candidate

    # PHASE_91_UAE_URL points at http://127.0.0.1:1 via the `vm100_down` fixture.
    return emit_alert_candidate(
        alert_type="discovery",
        producer_agent_id="chaos-agent",
        subject_id="CPIAUCSL",
        b13_internal_severity="info",
        explanation="chaos harness VM100-down probe",
        citations=["src:chaos-test"],
    )


# (name, driver, budget_seconds, hard_cap_seconds, acceptable_health_ids)
_DEP_SPECS = {
    # budget_mongo signal is the D-08 id; accept plain "mongo" too for latitude.
    "mongo": (_drive_mongo, 6.0, 8.0, ("mongo", "budget_mongo")),
    "postgres": (_drive_postgres, 7.0, 9.0, ("postgres",)),
    "qdrant": (_drive_qdrant, 7.0, 9.0, ("qdrant",)),
    # VM100 read-timeout budget (3.05, 15) → allow up to read-timeout + margin.
    "vm100": (_drive_vm100, 17.0, 20.0, ("phase91_uae", "agent_zero_http", "vm100")),
}


@pytest.mark.parametrize("dep", list(_DEP_SPECS))
def test_dependency_down_is_bounded_falls_back_and_signals(
    dep,
    mongo_down,
    postgres_down,
    qdrant_down,
    vm100_down,
):
    """Each downed dependency must fast-fail within budget, fall back, and emit a health signal."""
    from emitters.source_health_registry import SourceHealthRegistry

    driver, budget, cap, acceptable_ids = _DEP_SPECS[dep]
    failures: list[str] = []

    box, elapsed, still_running = _run_bounded(driver, cap=cap)

    # (1) bounded — the guarded call returns/raises within its timeout budget.
    if still_running:
        failures.append(
            f"{dep}: guarded call did not return within {cap}s "
            f"(un-timed client blocks well past its budget)"
        )
    elif elapsed >= budget:
        failures.append(f"{dep}: guarded call took {elapsed:.2f}s (>= {budget}s budget)")

    # (3) degrade signal — the downed dep is reported unavailable in the shared registry.
    # Computed before (2) because an OBSERVED fail-fast (raise + signal) is a valid
    # resilient outcome for propagate-idiom deps (postgres/qdrant), distinct from a
    # swallow-fallback (mongo/vm100). An unbounded hang or an UNOBSERVED raise is not.
    snap = SourceHealthRegistry.get_shared_instance().snapshot()
    present = [sid for sid in acceptable_ids if sid in snap]
    signalled_unavailable = bool(present) and all(
        snap[sid].available is False for sid in present
    )
    if not present:
        failures.append(
            f"{dep}: no health signal emitted — expected one of {acceptable_ids} "
            f"in snapshot (keys={sorted(snap)})"
        )
    elif any(snap[sid].available is not False for sid in present):
        failures.append(f"{dep}: health signal present but not marked unavailable")

    # (2) graceful degrade — either the turn completes on a deterministic fallback
    # (in-memory / DLQ / empty-safe, no raise) OR it fast-fails within budget AFTER
    # emitting the degrade signal (bounded, OBSERVED propagate). A raise WITHOUT a
    # degrade signal is an unobserved failure and is NOT resilient.
    if still_running:
        failures.append(f"{dep}: no fallback taken (call never returned)")
    elif box["exc"] is not None and not signalled_unavailable:
        failures.append(
            f"{dep}: raised {type(box['exc']).__name__} without emitting a degrade "
            f"signal (unobserved failure — expected fallback or bounded observed fail-fast)"
        )

    assert not failures, f"SC-2 chaos RED [{dep}]:\n  " + "\n  ".join(failures)
