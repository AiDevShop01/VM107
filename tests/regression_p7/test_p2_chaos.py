"""Phase 139 P7 — P2 dependency-timeout chaos regression (SC-1).

Guards (single-source `guarded_commits.GUARDED_COMMITS['test_p2_chaos']`):
  747117a  — feat(134-06): time the dependency clients (bounded connect/read).
  519f522  — feat(134-08): factory liveness probe degrades → the down host is
             OBSERVABLE (a bounded fast-fail that emits a health signal, not a
             silent broken lazy backend).
  0050c0d  — feat(134-03): neutralize the retry loop so a down dep fails within
             budget instead of retry-storming past it.

What this locks (the phase134 three-part acceptance, D-10 injected-fault posture):
  For each dependency redirected to an unreachable target (127.0.0.1:1 — NEVER a
  docker-stop of the shared dev stack), the guarded path must
    (1) return/raise within its configured timeout budget (wall-clock < budget),
    (2) degrade gracefully — either complete on a deterministic fallback OR fast-fail
        within budget AFTER emitting the degrade signal (bounded, observed propagate),
    (3) emit `_health.report(<dep>, available=False, …)` — asserted via
        SourceHealthRegistry.get_shared_instance().snapshot().
  An unbounded hang or an UNOBSERVED raise (raise with no health signal) is NOT
  resilient. Reverting any guarded sha reopens (1)/(2)/(3) → RED.

Consolidation note (139 D-03a): this hardens tests/phase134/test_chaos_dependency
_resilience.py into the named F5 suite. The three datastore deps (mongo/postgres/
qdrant) run HOST-CLEAN — their client libs (pymongo/psycopg2/qdrant-client) are on the
host py3.11 interpreter — via redirect fixtures defined inline here (D-10 safe). The
VM100/phase91 DLQ path pulls `jsonschema` (absent on host), so its chaos case is
`@pytest.mark.requires_deps` and runs under the Tier-2 venv (VM107/.venv); its import
is DEFERRED into the test body so host-clean collection stays clean.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from tests.regression_p7.guarded_commits import GUARDED_COMMITS

# Unreachable redirect target (D-10). Loopback:1 refuses/blackholes without disrupting
# any shared dev dependency — never a `docker stop`.
UNREACHABLE_HOST = os.getenv("A0_FAULT_UNREACHABLE_HOST", "127.0.0.1")
UNREACHABLE_PORT = int(os.getenv("A0_FAULT_UNREACHABLE_PORT", "1"))
UNREACHABLE_MONGO_URI = f"mongodb://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}"
UNREACHABLE_PG_URI = f"postgresql://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}/chaos"
UNREACHABLE_HTTP_URL = f"http://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}"


# ── D-10 redirect fixtures (consolidated from tests/phase134/conftest.py) ──────────

@pytest.fixture
def mongo_down(monkeypatch):
    """Redirect budget_tracker's MongoClient to an unreachable target (Mongo down)."""
    from core.boundary import budget_tracker

    real_client = budget_tracker.MongoClient

    def _redirect(_uri, *args, **kwargs):
        return real_client(UNREACHABLE_MONGO_URI, *args, **kwargs)

    monkeypatch.setattr(budget_tracker, "MongoClient", _redirect)
    return UNREACHABLE_MONGO_URI


@pytest.fixture
def postgres_down(monkeypatch):
    """Redirect belief_store's psycopg2.connect to an unreachable target (Postgres down)."""
    from core.belief import belief_store

    real_connect = belief_store.psycopg2.connect

    def _redirect(*_args, **_kwargs):
        return real_connect(UNREACHABLE_PG_URI)

    monkeypatch.setattr(belief_store.psycopg2, "connect", _redirect)
    return UNREACHABLE_PG_URI


@pytest.fixture
def qdrant_down(monkeypatch):
    """Redirect QdrantClient construction to an unreachable target (Qdrant down)."""
    import qdrant_client

    real_client = qdrant_client.QdrantClient

    def _redirect(*args, **kwargs):
        kwargs["host"] = UNREACHABLE_HOST
        kwargs["port"] = UNREACHABLE_PORT
        kwargs.pop("url", None)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(qdrant_client, "QdrantClient", _redirect)
    return (UNREACHABLE_HOST, UNREACHABLE_PORT)


# ── Wall-clock bounder (an un-timed hang cannot stall the suite) ───────────────────

def _run_bounded(fn, cap: float):
    """Run `fn` on a daemon thread; return (box, elapsed, still_running)."""
    box: dict = {"value": None, "exc": None}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — capture to assert the degrade contract
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True)
    start = time.monotonic()
    t.start()
    t.join(cap)
    elapsed = time.monotonic() - start
    return box, elapsed, t.is_alive()


# ── Per-dependency drivers (exercise the guarded path the fixture has redirected) ──

def _drive_mongo():
    from core.boundary.budget_tracker import MongoBudgetTracker

    tracker = MongoBudgetTracker("mongodb://chaos-redirected")
    return tracker.get_daily_total()


def _drive_postgres():
    from core.belief.belief_store import BeliefStore

    store = BeliefStore(
        postgres_url="postgresql://chaos-redirected/beliefs",
        mongo_url="mongodb://chaos-redirected/beliefs",
    )
    return store.query(subject_type="indicator", subject_id="CPIAUCSL")


def _drive_qdrant():
    from plugins._memory.backend.factory import create_backend

    # The FinGPT-guarded qdrant path (the memory factory) — a raw client carries no
    # health signal. The factory's bounded liveness probe fast-fails within the client
    # timeout and emits the `qdrant` degrade signal (519f522).
    return create_backend(
        {"memory_backend": "qdrant", "qdrant_host": "192.168.1.151", "qdrant_port": 6333},
        embedding_service=object(),
    )


# (name, driver, budget_seconds, hard_cap_seconds, acceptable_health_ids)
_DEP_SPECS = {
    "mongo": (_drive_mongo, 6.0, 8.0, ("mongo", "budget_mongo")),
    "postgres": (_drive_postgres, 7.0, 9.0, ("postgres",)),
    "qdrant": (_drive_qdrant, 7.0, 9.0, ("qdrant",)),
}


def _assert_bounded_degrades_signals(dep, driver, budget, cap, acceptable_ids):
    """Shared three-part acceptance (bounded / graceful degrade / health signal)."""
    from emitters.source_health_registry import SourceHealthRegistry

    failures: list[str] = []
    box, elapsed, still_running = _run_bounded(driver, cap=cap)

    # (1) bounded — the guarded call returns/raises within its timeout budget.
    if still_running:
        failures.append(
            f"{dep}: guarded call did not return within {cap}s (un-timed client hang)"
        )
    elif elapsed >= budget:
        failures.append(f"{dep}: guarded call took {elapsed:.2f}s (>= {budget}s budget)")

    # (3) degrade signal — the downed dep is reported unavailable in the shared registry.
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

    # (2) graceful degrade — deterministic fallback OR bounded observed fail-fast.
    if still_running:
        failures.append(f"{dep}: no fallback taken (call never returned)")
    elif box["exc"] is not None and not signalled_unavailable:
        failures.append(
            f"{dep}: raised {type(box['exc']).__name__} without emitting a degrade "
            f"signal (unobserved failure — not resilient)"
        )

    assert not failures, f"P2 chaos RED [{dep}]:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("dep", list(_DEP_SPECS))
def test_datastore_down_is_bounded_falls_back_and_signals(
    dep, mongo_down, postgres_down, qdrant_down
):
    """Each downed datastore must fast-fail within budget, degrade, and emit a health
    signal (host-clean: pymongo/psycopg2/qdrant-client on the host interpreter)."""
    driver, budget, cap, acceptable_ids = _DEP_SPECS[dep]
    _assert_bounded_degrades_signals(dep, driver, budget, cap, acceptable_ids)


@pytest.mark.requires_deps
def test_vm100_down_is_bounded_falls_back_and_signals(monkeypatch):
    """VM100/phase91 POST down → (connect,read)-timeout-bounded → DLQ fallback +
    `phase91_uae` signal. Tier-2 (jsonschema not on host) — import deferred."""
    monkeypatch.setenv("PHASE_91_UAE_URL", UNREACHABLE_HTTP_URL)

    def _drive_vm100():
        from core.alerts.phase91_emit import emit_alert_candidate

        return emit_alert_candidate(
            alert_type="discovery",
            producer_agent_id="chaos-agent",
            subject_id="CPIAUCSL",
            b13_internal_severity="info",
            explanation="F5 chaos VM100-down probe",
            citations=["src:chaos-test"],
        )

    _assert_bounded_degrades_signals(
        "vm100", _drive_vm100, 17.0, 20.0, ("phase91_uae", "agent_zero_http", "vm100")
    )


# ---------------------------------------------------------------------------
# Guarded-commit annotation self-check (host-clean)
# ---------------------------------------------------------------------------

def test_guarded_commits_include_p2_shas():
    """The single-source map carries the P2 chaos shas, so the revert harness
    (Plan 05) has a real RED to turn for each dependency-resilience fix."""
    shas = GUARDED_COMMITS["test_p2_chaos"]
    for base in ("747117a", "519f522", "0050c0d"):
        assert base in shas, f"missing P2 guarded sha {base}"
