"""CR-01 regression — Mongo ledgers report health at OP TIME, never off a lazy constructor.

Phase 134-09. ``SourceHealthRegistry.report()`` is last-writer-wins per ``source_id``. Before
this fix ``MongoTaskLedger`` / ``MongoProgressLedger`` stamped ``report("mongo", available=True)``
in ``__init__`` off a LAZY ``MongoClient`` that never contacted the server — which then clobbered
a correct op-time ``available=False`` (e.g. from ``belief_store``) under the shared ``"mongo"``
source_id, hiding a live outage from the DegradationPolicyEngine.

This test proves the fix:
  (a) construction emits NO ``available=True`` for ``"mongo"``,
  (b) the first op against a down Mongo emits ``available=False`` (op-time except branch),
  (c) a pre-existing ``available=False`` is NOT clobbered by ledger construction.

The autouse ``reset_source_health`` fixture (conftest.py) clears the shared registry around each
test so these assertions are deterministic.
"""
import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pymongo.errors import PyMongoError  # noqa: E402

# A lazy MongoClient never contacts the server at construction, so pointing at an
# unreachable target is safe and instant — construction must NOT stamp any health.
LAZY_DOWN_URI = "mongodb://127.0.0.1:1"


class _RaisingCollection:
    """Fake pymongo collection whose ops raise PyMongoError at CALL time (op-time outage)."""

    def find_one(self, *_a, **_k):
        raise PyMongoError("injected op-time mongo outage")

    def update_one(self, *_a, **_k):
        raise PyMongoError("injected op-time mongo outage")


def _snapshot():
    from emitters.source_health_registry import SourceHealthRegistry

    return SourceHealthRegistry.get_shared_instance().snapshot()


def test_task_ledger_construction_emits_no_available_true():
    from core.interfaces.task_ledger import MongoTaskLedger

    MongoTaskLedger(LAZY_DOWN_URI)  # lazy — no server contact, no health claim
    snap = _snapshot()
    assert "mongo" not in snap or snap["mongo"].available is not True


def test_progress_ledger_construction_emits_no_available_true():
    from core.interfaces.progress_ledger import MongoProgressLedger

    MongoProgressLedger(LAZY_DOWN_URI)
    snap = _snapshot()
    assert "mongo" not in snap or snap["mongo"].available is not True


def test_task_ledger_first_op_reports_unavailable():
    from core.interfaces.task_ledger import MongoTaskLedger

    ledger = MongoTaskLedger(LAZY_DOWN_URI)
    ledger._tasks = _RaisingCollection()

    result = asyncio.run(ledger.get_plan("task-1"))

    assert result == {}  # degrades to NoOp, never raises into the caller
    snap = _snapshot()
    assert "mongo" in snap and snap["mongo"].available is False
    # WR-04: sanitized failure_reason (exception class name, no host:port).
    assert snap["mongo"].failure_reason == "PyMongoError"


def test_task_ledger_update_reports_unavailable():
    from core.interfaces.task_ledger import MongoTaskLedger

    ledger = MongoTaskLedger(LAZY_DOWN_URI)
    ledger._tasks = _RaisingCollection()

    asyncio.run(ledger.update("task-1", {"status": "DONE"}))  # must not raise

    snap = _snapshot()
    assert "mongo" in snap and snap["mongo"].available is False


def test_progress_ledger_first_op_reports_unavailable():
    from core.execution_context import ExecutionContext
    from core.interfaces.progress_ledger import MongoProgressLedger

    ledger = MongoProgressLedger(LAZY_DOWN_URI)
    ledger._progress = _RaisingCollection()

    result = asyncio.run(ledger.get_next_action(ExecutionContext(task_id="task-1")))

    assert result is None  # degrades to NoOp
    snap = _snapshot()
    assert "mongo" in snap and snap["mongo"].available is False


def test_ledger_construction_does_not_clobber_prior_unavailable():
    from emitters.source_health_registry import SourceHealthRegistry
    from core.interfaces.progress_ledger import MongoProgressLedger
    from core.interfaces.task_ledger import MongoTaskLedger

    reg = SourceHealthRegistry.get_shared_instance()
    # Simulate belief_store's correct op-time degrade signal already being live.
    reg.report("mongo", available=False, failure_reason="ServerSelectionTimeoutError")

    # Constructing lazy ledgers must NOT flip that correct signal back to available=True.
    MongoTaskLedger(LAZY_DOWN_URI)
    MongoProgressLedger(LAZY_DOWN_URI)

    snap = reg.snapshot()
    assert snap["mongo"].available is False, (
        "ledger construction clobbered a correct op-time available=False (CR-01 regression)"
    )
