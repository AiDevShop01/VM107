"""Phase 137 (P5 — Tool-Scope Reconciliation & Capability Activation) shared fixtures.

Wave-0 scaffolding. This is the executable acceptance contract for the whole phase:
every module asserts through the REAL runtime hops (never a hand-rolled yaml parser):

  * ``core.registry.capability_registry.CapabilityRegistry`` — the authoritative
    scope store (advertising side, ``get_index_for_profile``; the canonical deny,
    ``is_capability_in_scope``).
  * ``helpers.tool_scope.apply_tool_scope`` — the profile-scope filter (matches
    ``entry["id"]``; the E-CRIT2 anchor).
  * ``helpers.tool_scope_guard.check_tool_scope_for_profile`` — the sole exec gate
    (agent.py:977).

Idiom mirrors:
  * ``tests/phase136/conftest.py`` — repo-root-on-sys.path bootstrap + autouse
    SourceHealthRegistry clear (import-guarded so collection never breaks) + the
    real-Qdrant ``qdrant_test_client`` fixture (session-scoped, read-only, dev only).
  * ``tests/phase135/test_scope_from_registry.py`` — real-registry init that
    snapshots ``CapabilityRegistry`` and restores ``_instance`` on teardown.

DEV-ONLY discipline (carried from 134/135/136): read-only against the live dev
registry / Qdrant; no fixture halts or targets shared containers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Repo root on sys.path so `core.*`, `helpers.*`, `tools.*`, `emitters.*` import
# under the container venv (mirrors phase136/conftest.py). From
# tests/phase137/conftest.py, two levels up == the VM107 root (== /a0 in-container).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# The authoritative scope store lives under <repo>/registry (bind-mounted :ro at
# /a0/registry in-container; CAPABILITY_REGISTRY_ROOT=/a0/registry on the service).
_REGISTRY_ROOT = Path(_REPO_ROOT) / "registry"
_PROFILE_DIR = _REGISTRY_ROOT / "agent_profile"
_TOOL_DIR = _REGISTRY_ROOT / "tool"


@pytest.fixture(autouse=True)
def reset_source_health():
    """Clear the shared SourceHealthRegistry before/after each test.

    Import-guarded so a registry import hiccup can never break collection of the
    phase-137 gate suite (mirrors phase136/conftest.py:35-50).
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
def reg():
    """Session-scoped snapshot of the REAL CapabilityRegistry.

    Initializes ``CapabilityRegistry`` against the live ``registry/`` tree ONCE per
    session (the boot loader path — never a hand-rolled parser), yields the frozen
    instance, and restores ``_instance`` on teardown. Guarded against a pre-existing
    singleton so a warm registry (some other import) never turns the whole suite into
    errors instead of clean pass/fail (LD-2 reload would raise).
    """
    from core.registry.capability_registry import CapabilityRegistry

    original = CapabilityRegistry._instance
    if original is None:
        CapabilityRegistry.initialize(_REGISTRY_ROOT)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = original


@pytest.fixture(scope="session")
def qdrant_test_client():
    """Session-scoped REAL local Qdrant client (dev stack only).

    Copied from ``tests/phase136/conftest.py:76-102`` for the later E-HIGH1
    CombinedRAG live proof (V-02 step 5). Session-scoped, so it is instantiated ONLY
    when a test explicitly requests it — the Wave-0 RED scaffolds do not, so no module
    that does not need Qdrant triggers this. ``QDRANT_HOST`` fail-fast (env-driven
    lock), 40x0.25s readiness poll, read-only.
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
