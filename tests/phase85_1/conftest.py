"""Phase 85.1 shared pytest fixtures.

Provides mocks for the BrainOrchestrator, GoalService, TieredBulkWriter,
and related infrastructure so tests run without a live MongoDB, Redis, or
Agent Zero instance.

Architecture rationale (WHY this shape):
-----------------------------------------
The dispatcher (Plan 02) calls:
    orchestrator._goal_service.on_task_completed(task_id)

For WS-chain tests (Plans 02/05) to observe executive_summary_writer
transitioning from BLOCKED -> PENDING, the mock on_task_completed side-effect
MUST actually mutate the collection mock so the next poll cycle sees
executive_summary_writer.blocked_by == [].  That is why mock_goal_service
uses a real-behaviour side_effect rather than a simple MagicMock() return.

Requires:
    - core.scheduling.goal_service.GoalService (spec source)
    - core.scheduling.macro_release_goal.BrainOrchestrator (spec source)
    - core.persistence.bulk_writer.TieredBulkWriter (spec source)
    - tests.phase85_1.fixtures.brain_state_documents (factory functions)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import spec types (graceful if not available at collection time)
# ---------------------------------------------------------------------------
try:
    from core.scheduling.goal_service import GoalService
except ImportError:  # pragma: no cover
    GoalService = object  # type: ignore[assignment,misc]

try:
    from core.scheduling.macro_release_goal import BrainOrchestrator
except ImportError:  # pragma: no cover
    BrainOrchestrator = object  # type: ignore[assignment,misc]

try:
    from core.persistence.bulk_writer import TieredBulkWriter
except ImportError:  # pragma: no cover
    TieredBulkWriter = object  # type: ignore[assignment,misc]

from tests.phase85_1.fixtures.brain_state_documents import (
    make_macro_release_goal_with_three_tasks,
)


# ---------------------------------------------------------------------------
# Fixture: mock_brain_state_collection
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_brain_state_collection() -> MagicMock:
    """MagicMock simulating a pymongo Collection.

    Maintains an in-memory ``_store`` dict so that ``find()``,
    ``find_one()``, and ``update_one(upsert=True)`` behave coherently
    across multiple fixture interactions.

    The store maps document ``_id`` (= goal_id or task_id) to the document
    dict.  Tests may pre-populate ``mock_brain_state_collection._store``
    before calling service code.
    """
    collection = MagicMock()
    collection._store: dict[str, dict] = {}

    def _find(filter_=None, *args, **kwargs):
        """Return matching documents from the in-memory store."""
        if not filter_:
            return list(collection._store.values())
        results = []
        for doc in collection._store.values():
            match = all(doc.get(k) == v for k, v in filter_.items())
            if match:
                results.append(dict(doc))
        return iter(results)

    def _find_one(filter_=None, *args, **kwargs):
        """Return first matching document from the in-memory store."""
        for doc in collection._store.values():
            if not filter_:
                return dict(doc)
            if all(doc.get(k) == v for k, v in filter_.items()):
                return dict(doc)
        return None

    def _update_one(filter_, update, upsert=False, *args, **kwargs):
        """Apply $set / $setOnInsert updates to the in-memory store."""
        doc_id = filter_.get("_id") or filter_.get("task_id") or filter_.get("goal_id")
        if doc_id is None:
            return MagicMock(matched_count=0, modified_count=0)

        existing = collection._store.get(doc_id, {})
        if "$set" in update:
            existing.update(update["$set"])
        if "$setOnInsert" in update and not existing:
            existing.update(update["$setOnInsert"])
        if upsert or doc_id in collection._store:
            collection._store[doc_id] = existing

        result = MagicMock()
        result.matched_count = 1
        result.modified_count = 1
        result.upserted_id = doc_id if upsert and doc_id not in collection._store else None
        return result

    collection.find.side_effect = _find
    collection.find_one.side_effect = _find_one
    collection.update_one.side_effect = _update_one

    return collection


# ---------------------------------------------------------------------------
# Fixture: mock_bulk_writer
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bulk_writer(mock_brain_state_collection: MagicMock) -> MagicMock:
    """MagicMock(spec=TieredBulkWriter) whose write_critical mutates collection.

    When dispatcher code calls ``bulk_writer.write_critical(doc_id, updates)``,
    the side_effect stores the update in ``mock_brain_state_collection._store``
    so subsequent ``find()`` / ``find_one()`` calls reflect the change.
    This mirrors production semantics where write_critical() issues an upsert
    into the same collection that reads come from.
    """
    writer = MagicMock(spec=TieredBulkWriter)

    def _write_critical(doc_id: str, updates: dict) -> None:
        existing = mock_brain_state_collection._store.get(doc_id, {})
        existing.update(updates)
        # Ensure _id is set for upsert coherency
        existing.setdefault("_id", doc_id)
        mock_brain_state_collection._store[doc_id] = existing

    writer.write_critical.side_effect = _write_critical
    return writer


# ---------------------------------------------------------------------------
# Fixture: mock_goal_service
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_goal_service(
    mock_bulk_writer: MagicMock,
    mock_brain_state_collection: MagicMock,
) -> MagicMock:
    """MagicMock(spec=GoalService) with real-behaviour on_task_completed.

    The on_task_completed side_effect removes ``task_id`` from every other
    task's ``blocked_by`` array in the collection, then updates those tasks
    in the store — mirroring production GoalService semantics.

    This is the key fixture for WS-chain integration tests: without the
    real-behaviour side_effect, exec_summary_writer never transitions
    from BLOCKED to PENDING after release_analyst + asset_exposure complete.
    """
    svc = MagicMock(spec=GoalService)
    svc.bulk_writer = mock_bulk_writer

    # Wire task_cache so svc.task_cache.collection resolves
    task_cache_mock = MagicMock()
    task_cache_mock.collection = mock_brain_state_collection

    def _task_cache_get(doc_id: str) -> dict | None:
        doc = mock_brain_state_collection._store.get(doc_id)
        return dict(doc) if doc else None

    task_cache_mock.get.side_effect = _task_cache_get
    svc.task_cache = task_cache_mock

    # Wire goal_cache so svc.goal_cache.get resolves
    goal_cache_mock = MagicMock()

    def _goal_cache_get(doc_id: str) -> dict | None:
        doc = mock_brain_state_collection._store.get(doc_id)
        return dict(doc) if doc else None

    goal_cache_mock.get.side_effect = _goal_cache_get
    svc.goal_cache = goal_cache_mock

    # Real-behaviour on_task_completed: unblock downstream tasks
    def _on_task_completed(task_id: str) -> None:
        """Remove task_id from blocked_by of every task in the store."""
        store = mock_brain_state_collection._store
        for doc_id, doc in list(store.items()):
            if not doc_id.startswith("task_"):
                continue
            blocked_by: list[str] = list(doc.get("blocked_by", []))
            if task_id in blocked_by:
                blocked_by.remove(task_id)
                store[doc_id]["blocked_by"] = blocked_by
                if not blocked_by:
                    store[doc_id]["status"] = "pending"

    svc.on_task_completed.side_effect = _on_task_completed

    return svc


# ---------------------------------------------------------------------------
# Fixture: mock_orchestrator
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_orchestrator(mock_goal_service: MagicMock) -> MagicMock:
    """MagicMock(spec=BrainOrchestrator) with _goal_service wired.

    ``notify_goal_completed`` is a recording spy: call_count and call_args_list
    are inspectable by WS-chain tests.
    """
    orc = MagicMock(spec=BrainOrchestrator)
    orc._goal_service = mock_goal_service

    # notify_goal_completed records calls (spy behaviour)
    _completed_goals: list[str] = []

    def _notify(goal_id: str) -> None:
        _completed_goals.append(goal_id)

    orc.notify_goal_completed.side_effect = _notify
    orc._completed_goals = _completed_goals

    return orc


# ---------------------------------------------------------------------------
# Fixture: mock_dispatch_agent_sync
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dispatch_agent_sync(monkeypatch) -> MagicMock:
    """Patches VM107.workers.agent_invocation._dispatch_agent_sync.

    Returns a callable mock that returns ``(raw_output_str, telemetry_dict)``
    keyed per profile_id.  Tests may configure ``mock_dispatch_agent_sync.side_effect``
    to raise exceptions or return custom payloads.

    Note: VM107.workers.agent_invocation does not exist yet (Plan 02 creates it).
    The patch is a no-op at collection time — the fixture records the patch
    target so Plan 02 can reference the same path.
    """
    mock_fn = MagicMock(
        return_value=(
            '{"result": "ok", "indicator_id": "CPIAUCSL"}',
            {"tokens_used": 100, "latency_ms": 500},
        )
    )
    # Attempt to patch; if module doesn't exist yet, store for later use
    try:
        monkeypatch.setattr(
            "VM107.workers.agent_invocation._dispatch_agent_sync",
            mock_fn,
        )
    except (ImportError, AttributeError):
        # Module not yet created — patch target will be valid after Plan 02
        pass
    return mock_fn


# ---------------------------------------------------------------------------
# Fixture: fixture_macro_release_goal_doc
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_macro_release_goal_doc(
    mock_brain_state_collection: MagicMock,
) -> dict:
    """Single canonical goal document for CPIAUCSL macro release analysis.

    Pre-populates mock_brain_state_collection._store with the goal document
    so ``goal_cache.get(goal_id)`` returns it.

    Returns the goal_doc dict.
    """
    goal_doc, task_docs = make_macro_release_goal_with_three_tasks(
        indicator_id="CPIAUCSL",
    )
    goal_id = goal_doc["goal_id"]

    # Seed the store so collection reads work
    mock_brain_state_collection._store[goal_id] = dict(goal_doc)
    mock_brain_state_collection._store[goal_id]["_id"] = goal_id

    for task_doc in task_docs:
        task_id = task_doc["task_id"]
        mock_brain_state_collection._store[task_id] = dict(task_doc)
        mock_brain_state_collection._store[task_id]["_id"] = task_id

    return goal_doc


# ---------------------------------------------------------------------------
# Fixture: fixture_macro_release_task_docs
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_macro_release_task_docs(
    fixture_macro_release_goal_doc: dict,
    mock_brain_state_collection: MagicMock,
) -> list[dict]:
    """Return the 3 task documents for the canonical CPIAUCSL goal.

    Reads them back from mock_brain_state_collection._store (already seeded
    by fixture_macro_release_goal_doc) to guarantee a single source of truth.

    Order: [release_analyst_task, asset_exposure_task, exec_summary_task]
    """
    task_ids = fixture_macro_release_goal_doc["task_ids"]
    store = mock_brain_state_collection._store
    return [dict(store[tid]) for tid in task_ids]


# ---------------------------------------------------------------------------
# Fixture: patched_build_default_orchestrator
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_build_default_orchestrator(monkeypatch, mock_orchestrator: MagicMock):
    """Patches core.scheduling.orchestrator_factory.build_default_orchestrator.

    Any code that calls ``build_default_orchestrator()`` at module import or
    runtime will receive ``mock_orchestrator`` instead of trying to connect to
    MongoDB + Redis.

    Returns the mock_orchestrator for assertions.
    """
    monkeypatch.setattr(
        "core.scheduling.orchestrator_factory.build_default_orchestrator",
        lambda: mock_orchestrator,
    )
    return mock_orchestrator
