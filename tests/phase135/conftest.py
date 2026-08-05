"""Phase 135 (P3 — Robust Responses & Honest Degradation) injected-fault fixtures.

Wave-1 scaffolding: the shared fixtures every downstream P3 plan's test consumes.
Mirrors the Phase 134 harness (`tests/phase134/conftest.py`) verbatim where possible —
same repo-root bootstrap, same `reset_source_health` autouse — and adds a D3-facing
`qdrant_search_raises` fixture (plan-03 consumer) for the memory-degraded-signal test.

⚠️ D-10 hard constraint (carried from 134): NEVER halt a shared dev dependency container.
   The shared dev Qdrant instance has other dev consumers depending on it. All fault
   injection here is monkeypatch / raise ONLY — this harness deliberately imports no
   container-control library and no fixture ever targets the shared Qdrant host.
"""
from __future__ import annotations

import os
import sys

import pytest

# Repo root on sys.path so `core.*`, `emitters.*`, `plugins.*` import under the container venv.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before and after each test.

    Makes `snapshot()[dep].available` assertions deterministic regardless of prior tests
    or process-wide emitter state (D3 reads/freshens this bus; downstream plans assert on it).
    """
    from emitters.source_health_registry import SourceHealthRegistry

    SourceHealthRegistry.get_shared_instance().clear()
    yield
    SourceHealthRegistry.get_shared_instance().clear()


@pytest.fixture
def qdrant_search_raises(monkeypatch):
    """Make `QdrantBackend.search` raise a ConnectionError (Qdrant unreachable at search time).

    Plan-03 (`test_recall_degraded_signal.py`) consumer. D3-02 reports the outage from
    INSIDE `search()`'s `except` block, so faulting `search` itself is the smallest
    injected-fault that drives the degraded surface without touching any real client.

    D-10 safe: monkeypatch/raise only — never halts a container, never the shared dev
    Qdrant instance. Returns the exception type so consumers can assert the no-leak
    `failure_reason == type(exc).__name__` (WR-04) convention without hard-coding a string.
    """
    from plugins._memory.backend.qdrant_backend import QdrantBackend

    async def _raise(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise ConnectionError("qdrant unreachable (injected fault)")

    monkeypatch.setattr(QdrantBackend, "search", _raise)
    return ConnectionError
