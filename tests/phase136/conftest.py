"""Phase 136 (P4 — Maximize Local Tooling / Cut External Coupling) shared fixtures.

Wave-0 scaffolding: the fixtures the three SC gates consume.

  * ``qdrant_test_client`` — a REAL local Qdrant client (mirrors
    ``tests/integration/conftest.py``'s ``qdrant_test_client``) pointed at the dev
    ``knowledge_base_v2`` collection via ``os.environ["QDRANT_HOST"]``. Drives the
    SC-1 local-default path once 136-03 lands the local reader. NEVER a
    testcontainer, NEVER a prod host (dev stack only).
  * ``fake_redis`` — a Django-free, in-process double recording every
    ``.publish(channel, payload)`` call (BLOCKER-2 DI pattern) for the SC-2
    publisher gate; injected as ``SnapshotInvalidationPublisher(redis_client=...)``.
  * ``reset_source_health`` (autouse) — clears the process-wide
    ``SourceHealthRegistry`` around each test so the SC-1 degrade-read is
    deterministic (mirrors ``tests/phase135/conftest.py``).

D-10 / dev-only discipline (carried from 134/135): fault injection is
monkeypatch/double ONLY — no fixture halts or targets the shared dev Qdrant/Redis
containers; the real-Qdrant fixture is read-only against the live dev instance.
"""
from __future__ import annotations

import os
import sys

import pytest

# Repo root on sys.path so `tools.*`, `services.*`, `emitters.*`, `plugins.*`,
# `helpers.*` import under the container venv (mirrors phase135/conftest.py).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before and after each test.

    Makes the SC-1 ``snapshot()["qdrant"].available`` degrade-read deterministic
    regardless of prior tests or process-wide emitter state. Import-guarded so a
    registry import hiccup can never break collection of the gate suite.
    """
    try:
        from emitters.source_health_registry import SourceHealthRegistry
    except Exception:  # noqa: BLE001 — never let a registry import break collection
        yield
        return
    SourceHealthRegistry.get_shared_instance().clear()
    yield
    SourceHealthRegistry.get_shared_instance().clear()


class _FakeRedis:
    """Minimal Redis double: records every publish as ``(channel, payload)``.

    Mirrors the redis-py ``.publish(channel, message)`` surface the
    ``SnapshotInvalidationPublisher`` calls (VM100 publisher :117-124). No network,
    no Django, no shared-container touch — a pure in-process recorder for the
    SC-2 DI gate.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel, message):  # redis-py signature
        self.published.append((channel, message))
        return 1  # redis returns the number of subscribers that received the message


@pytest.fixture
def fake_redis():
    """Injected fake redis for ``SnapshotInvalidationPublisher(redis_client=...)``."""
    return _FakeRedis()


@pytest.fixture(scope="session")
def qdrant_test_client():
    """Session-scoped REAL local Qdrant client (dev stack only).

    Mirrors ``tests/integration/conftest.py``: connects to the live dev Qdrant at
    ``os.environ["QDRANT_HOST"]`` (fail-fast if unset — the env-driven-config lock),
    with a 40x0.25s readiness poll. Read-only; drives the SC-1 local-default path
    against the real ``knowledge_base_v2`` collection once 136-03 lands.
    """
    import time

    from qdrant_client import QdrantClient

    host = os.environ["QDRANT_HOST"]  # fail-fast if unset (D-04 env-driven lock)
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
