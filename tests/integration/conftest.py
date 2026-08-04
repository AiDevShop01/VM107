"""Phase 48 Plan 08b — E2E golden integration tests.

Re-export the Plan 00 / Wave 0 fixtures (mongo_test_db, valid_hypothesis_id,
frozen_registry_snapshot_hash, mock_typed_wrappers, mock_emit_event) into
``tests/integration/`` so the 9 phase-48 goldens can use them without
scavenger-hunting.

Pytest doesn't propagate fixtures from a sibling-tree conftest, so this
shim imports the canonical surface from
``tests/core/agents/refinement_orchestrator/conftest.py``. Single source of
truth preserved; this file is a thin re-export shim (same pattern Plan 03
used at ``tests/core/agents/conftest.py``).
"""
from __future__ import annotations

from tests.core.agents.refinement_orchestrator.conftest import (  # noqa: F401
    frozen_registry_snapshot_hash,
    mock_emit_event,
    mock_typed_wrappers,
    mongo_test_db,
    valid_hypothesis_id,
)

# ─────────────────────────────────────────────────────────────────────────────
# Phase 133 (P1) — real-Qdrant D-08 perf-harness fixtures (ADDITIVE — do NOT
# remove the re-export shim above).
#
# These back `tests/integration/test_p1_recall_perf.py` (the four D-08 checks).
# They point at the REAL Qdrant (`os.environ["QDRANT_HOST"]`, 192.168.1.151:6333
# from inside the recreated vm107-agent-zero container) — NOT testcontainers
# (PATTERNS drift #3). Fixture *shape* copied from tests/phase87/conftest.py:69-101.
#
# `warm_recall_stack` / `reset_load_count` reference `BgeEmbeddingAdapter._get_model`
# as a classmethod and `._load_count`, which do not exist until Plan 02 lands the
# process-singleton + counter. Until then these fixtures are EXPECTED to error
# (that is the intended Wave-0 RED state — see 133-01-PLAN.md).
# ─────────────────────────────────────────────────────────────────────────────
import asyncio  # noqa: E402
import os  # noqa: E402

import pytest  # noqa: E402


def _import_bge_adapter():
    """Lazy sys.path-inject import of BgeEmbeddingAdapter (test_collection_separation.py:76-80 shape)."""
    import sys
    from pathlib import Path

    vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
    if str(vm107_path) not in sys.path:
        sys.path.insert(0, str(vm107_path))
    from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter

    return BgeEmbeddingAdapter


@pytest.fixture(scope="session")
def qdrant_test_client():
    """Session-scoped REAL Qdrant client with a 40×0.25s readiness poll.

    D-08 forbids mocks: this connects to the live dev Qdrant at
    ``os.environ["QDRANT_HOST"]`` (192.168.1.151:6333 in-container), NOT a
    testcontainer. Copies the readiness-poll shape from
    tests/phase87/conftest.py:69-101 but repoints the host (PATTERNS drift #3).
    """
    import time

    from qdrant_client import QdrantClient

    host = os.environ["QDRANT_HOST"]  # fail-fast if unset (env-driven config lock)
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
            f"real Qdrant at {host}:{port} never became ready (40×0.25s budget)"
        )
    yield client


@pytest.fixture(scope="session")
def warm_recall_stack(qdrant_test_client):
    """Preload the embedding model once so p95 / loop-stall tests run WARM (SC-4).

    Mirrors the D-01 async preload: ``await asyncio.to_thread(BgeEmbeddingAdapter._get_model)``.
    RED until Plan 02 makes ``_get_model`` a classmethod — calling it unbound
    (no instance) raises today, erroring this fixture on purpose.
    """
    BgeEmbeddingAdapter = _import_bge_adapter()
    asyncio.run(asyncio.to_thread(BgeEmbeddingAdapter._get_model))
    return BgeEmbeddingAdapter


@pytest.fixture
def reset_load_count():
    """Reset the class-level model singleton + load counter for a clean load-once measurement.

    Returns the ``BgeEmbeddingAdapter`` class so the test can assert on
    ``._load_count`` after firing N recalls. RED until Plan 02 lands the counter
    (today ``_load_count`` stays at the value set here — the load path never
    increments it — so ``== 1`` fails as intended).
    """
    BgeEmbeddingAdapter = _import_bge_adapter()
    BgeEmbeddingAdapter._model = None
    BgeEmbeddingAdapter._load_count = 0
    return BgeEmbeddingAdapter
