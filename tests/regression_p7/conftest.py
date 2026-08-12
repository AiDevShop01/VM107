"""Phase 139 (P7 — F5 regression suite) shared fixtures.

The named F5 suite that references and hardens the existing P0–P3 lock tests
(`tests/boot/`, `tests/phase134/`, `tests/phase135/`, `tests/integration/`).
Copies the phase135 bootstrap verbatim — same repo-root sys.path insert, same
`reset_source_health` autouse, same `qdrant_search_raises` injected-fault
fixture — and adds a sibling `reset_slo` autouse over the new SLORegistry
(Phase 139-01 Task 3).

⚠️ D-10 hard constraint (carried from 134/135): NEVER halt a shared dev
   dependency container. The shared dev Qdrant instance has other dev consumers.
   All fault injection here is monkeypatch / raise ONLY — this harness imports no
   container-control library and no fixture ever targets the shared Qdrant host.
"""
from __future__ import annotations

import os
import sys

import pytest

# Repo root on sys.path so `core.*`, `emitters.*`, `plugins.*` import under the
# container venv (and the host-clean fast loop). Verbatim from phase135 conftest.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before and after each test.

    Makes `snapshot()[dep].available` assertions deterministic regardless of prior
    tests or process-wide emitter state (the D3/chaos tests read/freshen this bus).
    """
    from emitters.source_health_registry import SourceHealthRegistry

    SourceHealthRegistry.get_shared_instance().clear()
    yield
    SourceHealthRegistry.get_shared_instance().clear()


@pytest.fixture(autouse=True)
def reset_slo():
    """Clear the shared SLORegistry before and after each test.

    Sibling to `reset_source_health` — the SLO capture singleton (Phase 139-01
    Task 3) is process-wide, so each SC-2 test starts from an empty registry.
    """
    from core.observability.slo_registry import SLORegistry

    SLORegistry.get_shared_instance().clear()
    yield
    SLORegistry.get_shared_instance().clear()


@pytest.fixture
def qdrant_search_raises(monkeypatch):
    """Make `QdrantBackend.search` raise a ConnectionError (Qdrant unreachable at search time).

    D3 consumer (`test_p3d3_degraded_cause.py`, Plan 02). The outage is reported
    from INSIDE `search()`'s `except` block, so faulting `search` itself is the
    smallest injected-fault that drives the degraded surface without touching any
    real client.

    D-10 safe: monkeypatch/raise only — never halts a container, never the shared
    dev Qdrant instance. Returns the exception type so consumers can assert the
    no-leak `failure_reason == type(exc).__name__` (WR-04) convention without
    hard-coding a string.
    """
    from plugins._memory.backend.qdrant_backend import QdrantBackend

    async def _raise(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise ConnectionError("qdrant unreachable (injected fault)")

    monkeypatch.setattr(QdrantBackend, "search", _raise)
    return ConnectionError
