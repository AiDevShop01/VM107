"""Phase 138 (P6 — Dead Code, Dedup & God-File Decomposition) shared fixtures.

Wave-0 scaffolding. These fixtures lock the PRE-CHANGE behavior contract so every
later subtractive edit (delete/dedup/extract) is bisectable against a fixed net
(D-06 bisectability). This conftest is copied near-verbatim from
``tests/phase137/conftest.py`` — same DEV-only, read-only discipline.

Reused from the phase137 conftest:
  * Repo-root-on-sys.path bootstrap so ``core.*``, ``helpers.*``, ``tools.*``,
    ``plugins.*``, ``emitters.*`` import under the container venv (/a0 in-container).
  * ``reset_source_health`` autouse fixture — import-guarded ``SourceHealthRegistry``
    clear before/after each test (the factory/degrade paths trip the bus otherwise).
  * ``qdrant_test_client`` session fixture — real dev Qdrant, ``QDRANT_HOST``
    fail-fast, 40x0.25s readiness poll, read-only. Session-scoped so it is only
    instantiated when a test explicitly requests it (the Wave-0 RED scaffolds do
    not, so no Qdrant contact for the walk-tree / parity tests).

DEV-ONLY discipline (carried from 134/135/136/137): read-only against the live dev
Qdrant; no fixture halts or targets shared containers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Repo root on sys.path so `core.*`, `helpers.*`, `tools.*`, `plugins.*`,
# `emitters.*` import under the container venv (mirrors phase137/conftest.py:35-37).
# From tests/phase138/conftest.py, two levels up == the VM107 root (== /a0 in-container).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before/after each test.

    Import-guarded so a registry import hiccup can never break collection of the
    phase-138 Wave-0 suite (mirrors phase137/conftest.py:46-60).
    """
    try:
        from emitters.source_health_registry import SourceHealthRegistry
    except Exception:  # noqa: BLE001 — never let a registry import break collection
        yield
        return
    SourceHealthRegistry.get_shared_instance().clear()
    yield
    SourceHealthRegistry.get_shared_instance().clear()


@pytest.fixture(scope="session")
def qdrant_test_client():
    """Session-scoped REAL local Qdrant client (dev stack only).

    Copied from ``tests/phase137/conftest.py:82-109`` for any factory test that needs
    a live client. Session-scoped, so it is instantiated ONLY when a test explicitly
    requests it — the Wave-0 RED scaffolds do not, so no module that does not need
    Qdrant triggers this. ``QDRANT_HOST`` fail-fast (env-driven lock), 40x0.25s
    readiness poll, read-only.
    """
    import time

    from qdrant_client import QdrantClient

    host = os.environ["QDRANT_HOST"]  # fail-fast if unset (env-driven-config lock)
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    for _attempt in range(40):  # 40 * 0.25s = 10s budget
        try:
            client.get_collections()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    else:
        raise RuntimeError(
            f"real dev Qdrant at {host}:{port} never became ready (40x0.25s budget)"
        )
    yield client
