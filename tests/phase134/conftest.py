"""SC-2 chaos harness fixtures — per-dependency monkeypatch-redirect (D-10 safe).

Phase 134 Wave 0. These fixtures inject a *down dependency* WITHOUT ever touching the
shared dev stack (Mongo/Postgres/Qdrant @ 192.168.1.151). Each `*_down` fixture
monkeypatches the client constructor / connection target used by the guarded module so
it points at an **unreachable** target (`127.0.0.1:1`) — never a `docker stop`. This is the
CI-native chaos form (Phase 139-absorbable); `scripts/verify_dependency_resilience.sh`
gives the higher-fidelity shell form driven by the same per-dep env toggles.

⚠️ D-10 hard constraint: NEVER docker-stop a shared dev dependency. Redirect only.
   There is deliberately NO `import docker` anywhere in this harness.

Each fixture ALSO sets its per-dep `A0_FAULT_INJECT_*_DOWN` toggle for the run so the
env-gated shell path (verify_dependency_resilience.sh) and the pytest merge gate exercise
the same activation surface; the toggles default dormant (unset) outside a chaos run.
"""
from __future__ import annotations

import os
import sys

import pytest

# Repo root on sys.path so `core.*`, `emitters.*`, `plugins.*` import under the container venv.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Unreachable redirect target (D-10). Loopback:1 refuses/blackholes without disrupting any
# shared dev dependency. Overridable for a blackhole (e.g. 10.255.255.1) via env if needed.
UNREACHABLE_HOST = os.getenv("A0_FAULT_UNREACHABLE_HOST", "127.0.0.1")
UNREACHABLE_PORT = int(os.getenv("A0_FAULT_UNREACHABLE_PORT", "1"))
UNREACHABLE_MONGO_URI = f"mongodb://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}"
UNREACHABLE_PG_URI = f"postgresql://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}/chaos"
UNREACHABLE_HTTP_URL = f"http://{UNREACHABLE_HOST}:{UNREACHABLE_PORT}"

# Per-dep env toggles (mirror Phase 132 A0_FAULT_INJECT_* convention). The shell verifier
# sets exactly one of these before `docker compose up -d --force-recreate`.
TOGGLE_MONGO = "A0_FAULT_INJECT_MONGO_DOWN"
TOGGLE_POSTGRES = "A0_FAULT_INJECT_POSTGRES_DOWN"
TOGGLE_QDRANT = "A0_FAULT_INJECT_QDRANT_DOWN"
TOGGLE_VM100 = "A0_FAULT_INJECT_VM100_DOWN"


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before and after each test.

    Makes `snapshot()[dep].available` assertions deterministic regardless of prior tests
    or process-wide emitter state.
    """
    from emitters.source_health_registry import SourceHealthRegistry

    SourceHealthRegistry.get_shared_instance().clear()
    yield
    SourceHealthRegistry.get_shared_instance().clear()


@pytest.fixture
def mongo_down(monkeypatch):
    """Redirect budget_tracker's MongoClient to an unreachable target (Mongo down).

    Wraps the module-level `MongoClient` so any construction inside budget_tracker connects
    to 127.0.0.1:1 while preserving the module's own (currently un-timed) kwargs — so today
    the first op blocks on pymongo's ~30s default server-selection window (RED).
    """
    from core.boundary import budget_tracker

    monkeypatch.setenv(TOGGLE_MONGO, "1")
    real_client = budget_tracker.MongoClient

    def _redirect(_uri, *args, **kwargs):
        return real_client(UNREACHABLE_MONGO_URI, *args, **kwargs)

    monkeypatch.setattr(budget_tracker, "MongoClient", _redirect)
    return UNREACHABLE_MONGO_URI


@pytest.fixture
def postgres_down(monkeypatch):
    """Redirect belief_store's psycopg2.connect to an unreachable target (Postgres down).

    Wraps the module-referenced `psycopg2.connect` so BeliefStore's connect targets
    127.0.0.1:1; today it is un-timed and raises with no fallback / no health signal (RED).
    """
    from core.belief import belief_store

    monkeypatch.setenv(TOGGLE_POSTGRES, "1")
    real_connect = belief_store.psycopg2.connect

    def _redirect(*_args, **_kwargs):
        return real_connect(UNREACHABLE_PG_URI)

    monkeypatch.setattr(belief_store.psycopg2, "connect", _redirect)
    return UNREACHABLE_PG_URI


@pytest.fixture
def qdrant_down(monkeypatch):
    """Redirect QdrantClient construction to an unreachable target (Qdrant down).

    Wraps `qdrant_client.QdrantClient` (imported lazily inside the memory factory) so any
    client targets 127.0.0.1:1; today the guarded op is un-timed with no fallback / signal (RED).
    """
    import qdrant_client

    monkeypatch.setenv(TOGGLE_QDRANT, "1")
    real_client = qdrant_client.QdrantClient

    def _redirect(*args, **kwargs):
        kwargs["host"] = UNREACHABLE_HOST
        kwargs["port"] = UNREACHABLE_PORT
        kwargs.pop("url", None)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(qdrant_client, "QdrantClient", _redirect)
    return (UNREACHABLE_HOST, UNREACHABLE_PORT)


@pytest.fixture
def vm100_down(monkeypatch):
    """Point the Phase 91 UAE / VM100 POST target at an unreachable URL (VM100 down).

    Sets PHASE_91_UAE_URL to http://127.0.0.1:1 so the guarded `requests.post` in
    phase91_emit hits a refusing/blackhole peer; today it is un-timed and emits no
    `phase91_uae` health signal (RED), though it already routes to the DLQ.
    """
    monkeypatch.setenv(TOGGLE_VM100, "1")
    monkeypatch.setenv("PHASE_91_UAE_URL", UNREACHABLE_HTTP_URL)
    return UNREACHABLE_HTTP_URL
