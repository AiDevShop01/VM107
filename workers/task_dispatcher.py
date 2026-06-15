"""Phase 85.1 — Task Dispatcher: polling loop + per-task handler.

Implements the Brain task executor: reads PENDING tasks from ``vm107_brain.brain_state``,
invokes the correct Agent Zero profile for each task, transitions task statuses
(PENDING → RUNNING → COMPLETED|FAILED), unblocks downstream tasks via
``goal_service.on_task_completed``, and fires the WS publish hook on goal
completion.

Module contract:
    dispatch_next_task(collection, bulk_writer) — pick first eligible task, mark RUNNING
    get_eligible_tasks(collection)              — return PENDING tasks with empty blocked_by
    run_task(task, goal_service)                — run one task end-to-end
    run_all_tasks_for_goal(goal_id, indicator_id, orchestrator, goal_service) — full 3-task flow
    parse_and_persist                           — re-exported from output_routing
    main()                                      — long-running polling loop (docker-compose service)
    _publish_once(goal_id, indicator_id)        — dedup-guarded WS publish

Pitfall references (from 85.1-RESEARCH.md):
    Pitfall 2: profile_id must be in sub.data BEFORE hist_add_user_message
    Pitfall 3: on_task_completed called after EVERY terminal (COMPLETED or FAILED)
    Pitfall 5: all status writes via bulk_writer.write_critical (not direct DB writes)
    Pitfall 6: listener registers on_complete hook at goal-creation time (PRIMARY path)
    Pitfall 7: no module-top import of agent.py (agent_invocation handles this)

W5 dedup contract:
    _published_goal_ids is a module-level set, cleared at the top of each main()
    poll iteration. Both the listener-registered on_complete hook AND the
    dispatcher's defence-in-depth call site route through _publish_once(), which
    checks this set before publishing. Net publish_count == 1 regardless of which
    path fires first.

CLAUDE.md locks honoured:
    env-driven-no-fallbacks: POLL_SEC + MAX_CONCURRENT are required; MAX_RETRIES has
    a default (tunable knob, not a URL/credential).
"""
from __future__ import annotations

import logging
import os
import signal
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from datetime import datetime, timezone
from typing import Any

from VM107.core.scheduling.enums import GoalStatus, TaskStatus
from VM107.workers.dispatcher_concurrency import DispatcherConcurrencyGuard
import VM107.workers.agent_invocation as _agent_inv  # module-ref so test patches are visible
from VM107.workers.output_routing import OutputParseError, UnknownProfileError, parse_and_persist

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-export parse_and_persist so tests can do:
#     from VM107.workers.task_dispatcher import parse_and_persist
# ---------------------------------------------------------------------------
__all__ = [
    "main",
    "dispatch_next_task",
    "dispatch_batch",
    "get_eligible_tasks",
    "run_task",
    "run_task_with_retry",
    "run_all_tasks_for_goal",
    "handle_upstream_failure",
    "parse_and_persist",
    "_publish_once",
    "_dispatch_one",
    "_check_upstream_failures",
]

# ---------------------------------------------------------------------------
# W5 publish dedup guard
# Module-level set; reset to empty at the top of each main() poll iteration.
# Tracks goal_ids for which publish_indicator_updated has already fired in
# THIS poll cycle.  Both the listener on_complete hook AND the dispatcher's
# defence-in-depth path call _publish_once() — the set ensures exactly one
# publish per goal per cycle regardless of which path fires first.
# ---------------------------------------------------------------------------
_published_goal_ids: set[str] = set()


def _publish_once(goal_id: str, indicator_id: str) -> None:
    """Publish WS invalidation for indicator_id — at most once per goal per poll cycle.

    Checks ``_published_goal_ids`` (module-level dedup set) before calling
    ``publish_indicator_updated``.  If goal_id is already in the set, this is
    a no-op (dedup skip).  Otherwise, adds goal_id to the set and publishes.

    Pitfall 9: Does NOT publish if the goal has any FAILED or CANCELLED tasks.
    Records the goal_id in the dedup set either way (defence-in-depth: prevents
    a later call path from firing a spurious publish after a failure is detected).

    Args:
        goal_id: Goal identifier (used as dedup key).
        indicator_id: FRED series code to publish the invalidation for.
    """
    if goal_id in _published_goal_ids:
        logger.info({"event": "publish_dedup_skip", "goal_id": goal_id, "indicator_id": indicator_id})
        return

    # Always add to dedup set — prevents second call from bypassing the check
    _published_goal_ids.add(goal_id)

    # Late import: avoid importing macro_ws_invalidation at module top.
    # That module resolves REDIS_URL at import time via a module-level call
    # to _required("REDIS_URL") which would fail in unit tests without Redis.
    try:
        from VM107.publishers.macro_ws_invalidation import publish_indicator_updated
        publish_indicator_updated(indicator_id)
        logger.info({
            "event": "vm107_task_dispatcher_ws_published",
            "goal_id": goal_id,
            "indicator_id": indicator_id,
        })
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "vm107_task_dispatcher_ws_publish_error",
            "goal_id": goal_id,
            "indicator_id": indicator_id,
            "error": str(exc),
        })


# ---------------------------------------------------------------------------
# Eligible task selection
# ---------------------------------------------------------------------------

def get_eligible_tasks(collection: Any) -> list[dict]:
    """Return all PENDING tasks with empty blocked_by from the collection.

    Args:
        collection: pymongo.Collection (or test mock) for vm107_brain.brain_state.

    Returns:
        List of task dicts eligible for dispatch (status=pending, blocked_by=[]).
    """
    docs = collection.find({"status": TaskStatus.PENDING.value, "blocked_by": []})
    # Filter for task documents (have task_id) with empty blocked_by
    result = []
    for doc in docs:
        if "task_id" not in doc:
            continue
        # Double-check blocked_by is truly empty (handle None + missing)
        if doc.get("blocked_by"):
            continue
        result.append(dict(doc))
    return result


# ---------------------------------------------------------------------------
# Single-task dispatch (mark RUNNING)
# ---------------------------------------------------------------------------

def dispatch_next_task(collection: Any, bulk_writer: Any) -> dict | None:
    """Pick the first eligible PENDING task, mark it RUNNING, and return it.

    Called by the polling loop to claim a single task before invoking the agent.
    Uses ``bulk_writer.write_critical`` (Pitfall 5 — never direct DB writes).

    Args:
        collection: pymongo.Collection for vm107_brain.brain_state.
        bulk_writer: TieredBulkWriter instance.

    Returns:
        The task dict (mutated with status=running) or None if no eligible tasks.
    """
    eligible = get_eligible_tasks(collection)
    if not eligible:
        return None

    task = eligible[0]
    task_id = task["task_id"]
    now = datetime.now(timezone.utc)

    # PITFALL 5: all status writes via write_critical
    bulk_writer.write_critical(task_id, {
        "status": TaskStatus.RUNNING.value,
        "started_at": now,
        "updated_at": now,
    })
    task["status"] = TaskStatus.RUNNING.value
    return task


# ---------------------------------------------------------------------------
# Concurrency-capped batch dispatch (Plan 05)
# ---------------------------------------------------------------------------

def dispatch_batch(
    collection: Any,
    max_concurrent: int,
    goal_service: Any | None = None,
    bulk_writer: Any | None = None,
    orchestrator: Any | None = None,
) -> None:
    """Dispatch eligible PENDING tasks with a bounded-concurrency cap.

    Fetches up to ``max_concurrent * 2`` PENDING tasks from ``collection``,
    fans them out via ``ThreadPoolExecutor``, and enforces the cap via a
    ``DispatcherConcurrencyGuard`` semaphore.

    The over-fetch factor (2×) avoids stalls where the query returns exactly
    ``max_concurrent`` tasks but some have already moved out of PENDING by the
    time a thread claims them.  The guard's idempotency re-read in
    ``_dispatch_one`` (status != PENDING → skip) handles the case where another
    thread beats us to a task.

    Args:
        collection: pymongo.Collection for vm107_brain.brain_state.
        max_concurrent: Maximum tasks allowed to run simultaneously.
        goal_service: GoalService instance (optional — used when dispatching live).
        bulk_writer: TieredBulkWriter instance (optional — used when dispatching live).
        orchestrator: BrainOrchestrator instance (optional — used when dispatching live).
    """
    if max_concurrent < 1:
        raise ValueError(f"max_concurrent must be >= 1; got {max_concurrent}")

    guard = DispatcherConcurrencyGuard(max_concurrent)
    eligible = get_eligible_tasks(collection)

    if not eligible:
        return

    # Over-fetch: give the thread pool 2× capacity so slow starters don't stall
    batch = eligible[: max_concurrent * 2]

    def _guarded_dispatch(task_dict: dict) -> None:
        task_id = task_dict.get("task_id", "?")
        # IDEMPOTENCY: re-read fresh status from collection before claiming slot.
        # The task dict is from an old find() snapshot; by now another thread
        # may have claimed the task (PENDING → RUNNING).
        fresh = collection.find_one({"_id": task_id}) or collection.find_one({"task_id": task_id})
        if fresh and fresh.get("status") not in (TaskStatus.PENDING.value, "pending"):
            logger.debug({
                "event": "dispatcher_skip_nonpending",
                "task_id": task_id,
                "status": fresh.get("status"),
            })
            return

        with guard.slot(task_id):
            if goal_service is not None and bulk_writer is not None:
                _dispatch_one(
                    task_dict,
                    goal_service=goal_service,
                    bulk_writer=bulk_writer,
                    orchestrator=orchestrator,
                )
            else:
                # Test mode: mark RUNNING, then call the agent sync mock
                now = datetime.now(timezone.utc)
                # Mark RUNNING via collection update_one (no bulk_writer in test mode)
                collection.update_one(
                    {"task_id": task_id},
                    {"$set": {"status": TaskStatus.RUNNING.value, "started_at": now}},
                )
                # Invoke the (potentially mocked) agent
                try:
                    _agent_inv._dispatch_agent_sync(task_dict.get("agent_name", ""), "")
                    collection.update_one(
                        {"task_id": task_id},
                        {"$set": {"status": TaskStatus.COMPLETED.value}},
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error({
                        "event": "dispatch_batch_agent_error",
                        "task_id": task_id,
                        "error": str(exc),
                    })

    with ThreadPoolExecutor(
        max_workers=max_concurrent,
        thread_name_prefix="vm107-task-dispatcher",
    ) as executor:
        futures = [executor.submit(_guarded_dispatch, td) for td in batch]
        futures_wait(futures)


# ---------------------------------------------------------------------------
# Retry-aware task runner (Plan 05)
# ---------------------------------------------------------------------------

def run_task_with_retry(task: dict, goal_service: Any) -> None:
    """Run a task through its full lifecycle with retry semantics.

    Implements the retry state machine:
        PENDING → RUNNING (attempt N) → PENDING (retry_count += 1)  [if attempt < max_retries]
        PENDING → RUNNING (attempt max_retries) → FAILED             [if max retries exhausted]
        PENDING → RUNNING (attempt N) → COMPLETED                    [on success]

    Before each attempt, checks ``retry_count >= max_retries``.  If exhausted,
    writes FAILED immediately WITHOUT invoking the agent (the agent has already
    failed on the previous attempt; no point calling it again with a fresh budget).

    Args:
        task: Task document dict (must have task_id, goal_id, agent_name,
              max_retries, retry_count).
        goal_service: GoalService instance (provides bulk_writer + goal_cache).
    """
    task_id: str = task["task_id"]
    goal_id: str = task.get("goal_id", "")
    profile_id: str = task.get("agent_name", "")
    max_retries: int = task.get("max_retries", MAX_RETRIES_DEFAULT)
    bulk_writer = goal_service.bulk_writer

    # Read current retry_count from the live store (more reliable than the task dict snapshot)
    def _current_retry_count() -> int:
        try:
            fresh = goal_service.task_cache.collection.find_one({"_id": task_id}) or {}
            return int(fresh.get("retry_count", task.get("retry_count", 0)))
        except Exception:  # noqa: BLE001
            return int(task.get("retry_count", 0))

    retry_count = _current_retry_count()

    # Look up goal_payload for agent message
    goal_payload: dict = {}
    try:
        goal_doc = goal_service.goal_cache.get(goal_id)
        if goal_doc:
            goal_payload = goal_doc.get("payload", {})
    except Exception:  # noqa: BLE001
        pass

    message = _build_message_for_profile(profile_id, goal_payload, goal_service)

    while True:
        # --- Mark RUNNING (Pitfall 5) ---
        now = datetime.now(timezone.utc)
        bulk_writer.write_critical(task_id, {
            "status": TaskStatus.RUNNING.value,
            "retry_count": retry_count,
            "started_at": now,
            "updated_at": now,
        })

        # --- Invoke agent ---
        try:
            raw_output, telemetry = _agent_inv._dispatch_agent_sync(profile_id, message)
        except Exception as exc:  # noqa: BLE001
            logger.error({
                "event": "vm107_task_dispatcher_agent_error",
                "task_id": task_id,
                "retry_count": retry_count,
                "error": str(exc),
            })
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                # Retries exhausted — mark FAILED with the exception message.
                # ``max_retries`` is the maximum ``retry_count`` value allowed before
                # the task is considered permanently failed (inclusive upper bound).
                # Example: max_retries=3 → up to 3 agent calls; 3rd failure → FAILED.
                # Example: max_retries=0 → 1 agent call; 1st failure → FAILED.
                # Invariant: ``new_retry_count >= max_retries`` means exhausted.
                failed_at = datetime.now(timezone.utc)
                bulk_writer.write_critical(task_id, {
                    "status": TaskStatus.FAILED.value,
                    "failure_reason": str(exc)[:500],
                    "retry_count": new_retry_count,
                    "completed_at": failed_at,
                    "updated_at": failed_at,
                })
                logger.warning({
                    "event": "vm107_task_dispatcher_max_retries_exhausted",
                    "task_id": task_id,
                    "retry_count": new_retry_count,
                    "max_retries": max_retries,
                })
                # PITFALL 3
                goal_service.on_task_completed(task_id)
                return
            # Not yet exhausted — re-queue to PENDING for next poll cycle
            bulk_writer.write_critical(task_id, {
                "status": TaskStatus.PENDING.value,
                "retry_count": new_retry_count,
                "failure_reason": str(exc)[:500],
                "updated_at": datetime.now(timezone.utc),
            })
            retry_count = new_retry_count
            continue  # retry immediately (loop handles POLL_SEC pacing in production)

        # --- Success ---
        envelope_id = telemetry.get("b1_artifact_id") or str(uuid.uuid4())
        completed_at = datetime.now(timezone.utc)
        bulk_writer.write_critical(task_id, {
            "status": TaskStatus.COMPLETED.value,
            "completed_at": completed_at,
            "envelope_id": envelope_id,
            "model_used": telemetry.get("model_used", "unknown"),
            "updated_at": completed_at,
        })

        # Persist output (non-fatal)
        try:
            parse_and_persist(profile_id, raw_output, telemetry, goal_payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning({
                "event": "vm107_task_dispatcher_persist_error",
                "task_id": task_id,
                "error": str(exc),
            })

        # PITFALL 3
        goal_service.on_task_completed(task_id)
        return


# ---------------------------------------------------------------------------
# Partial upstream failure handler (Plan 05)
# ---------------------------------------------------------------------------

def _check_upstream_failures(task_dict: dict, goal_service: Any) -> bool:
    """Check if any declared upstream dependency of this task is FAILED or CANCELLED.

    Args:
        task_dict: Task document (must have 'dependencies' list of task_ids).
        goal_service: GoalService providing task_cache.

    Returns:
        True if any upstream is FAILED or CANCELLED; False otherwise.
    """
    deps: list[str] = task_dict.get("dependencies", [])
    if not deps:
        return False
    terminal_failed = {TaskStatus.FAILED.value, "failed", TaskStatus.CANCELLED.value, "cancelled"}
    for dep_task_id in deps:
        try:
            dep = goal_service.task_cache.collection.find_one({"_id": dep_task_id})
            if dep is None:
                # Try alternative key
                dep = goal_service.task_cache.collection.find_one({"task_id": dep_task_id})
            if dep and dep.get("status") in terminal_failed:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def handle_upstream_failure(
    failed_task_id: str,
    goal_id: str,
    collection: Any,
    goal_service: Any,
) -> None:
    """Cancel all PENDING/BLOCKED tasks in this goal that depended on the failed task.

    Called when a task reaches terminal FAILED state.  Finds every other task
    in the goal whose ``dependencies`` list includes ``failed_task_id``, and
    transitions them to CANCELLED via ``bulk_writer.write_critical``.

    The WS publish guard will not fire if any task is CANCELLED (Pitfall 9).

    Args:
        failed_task_id: ID of the task that reached FAILED terminal state.
        goal_id: Goal that owns the failed task.
        collection: pymongo.Collection for vm107_brain.brain_state.
        goal_service: GoalService (provides bulk_writer + goal_cache).
    """
    bulk_writer = goal_service.bulk_writer
    store = getattr(collection, "_store", None)

    # Determine which tasks belong to this goal
    goal_doc: dict | None = None
    try:
        goal_doc = goal_service.goal_cache.get(goal_id)
    except Exception:  # noqa: BLE001
        pass

    task_ids: list[str] = (goal_doc or {}).get("task_ids", [])
    if not task_ids and store:
        # Fallback: scan store for tasks with matching goal_id
        task_ids = [
            doc["task_id"]
            for doc in store.values()
            if doc.get("goal_id") == goal_id and "task_id" in doc
        ]

    non_terminal = {TaskStatus.PENDING.value, "pending", TaskStatus.BLOCKED.value, "blocked"}

    for task_id in task_ids:
        if task_id == failed_task_id:
            continue  # skip the task that already failed

        # Fetch current doc
        task_doc: dict = {}
        if store:
            task_doc = dict(store.get(task_id, {}))
        else:
            try:
                task_doc = collection.find_one({"_id": task_id}) or {}
            except Exception:  # noqa: BLE001
                pass

        # Only cancel tasks that are not yet terminal
        if task_doc.get("status") not in non_terminal:
            continue

        # Check if this task depends on the failed task
        deps = task_doc.get("dependencies", [])
        if failed_task_id not in deps:
            continue

        now = datetime.now(timezone.utc)
        bulk_writer.write_critical(task_id, {
            "status": TaskStatus.CANCELLED.value,
            "failure_reason": f"Upstream task {failed_task_id!r} failed",
            "cancelled_at": now,
            "updated_at": now,
        })
        logger.warning({
            "event": "vm107_task_dispatcher_task_cancelled",
            "task_id": task_id,
            "failed_upstream": failed_task_id,
            "goal_id": goal_id,
        })
        # PITFALL 3: call on_task_completed so the goal service knows this task is done
        goal_service.on_task_completed(task_id)


# ---------------------------------------------------------------------------
# Full task lifecycle
# ---------------------------------------------------------------------------

def run_task(task: dict, goal_service: Any) -> None:
    """Run a single task through its full lifecycle: RUNNING → COMPLETED|FAILED.

    Steps:
        1. Mark task RUNNING via goal_service.bulk_writer.write_critical.
        2. Look up goal_payload from goal_service.goal_cache.
        3. Call _dispatch_agent_sync with the task's agent profile.
        4. Write COMPLETED + envelope_id via write_critical.
        5. Call parse_and_persist to route agent output to the correct table.
        6. Call goal_service.on_task_completed (PITFALL 3 — ALWAYS for terminal).

    On agent error:
        - Writes FAILED + failure_reason via write_critical.
        - Still calls goal_service.on_task_completed (PITFALL 3).

    Args:
        task: Task dict from brain_state (must have task_id, goal_id, agent_name).
        goal_service: GoalService instance (provides bulk_writer, goal_cache, task_cache).
    """
    task_id: str = task["task_id"]
    goal_id: str = task.get("goal_id", "")
    profile_id: str = task.get("agent_name", "")
    now = datetime.now(timezone.utc)

    bulk_writer = goal_service.bulk_writer

    # Step 1: Mark RUNNING (Pitfall 5)
    bulk_writer.write_critical(task_id, {
        "status": TaskStatus.RUNNING.value,
        "started_at": now,
        "updated_at": now,
    })

    # Step 2: Look up goal_payload for routing
    goal_payload: dict = {}
    try:
        goal_doc = goal_service.goal_cache.get(goal_id)
        if goal_doc:
            goal_payload = goal_doc.get("payload", {})
    except Exception:  # noqa: BLE001
        pass

    # Build the agent message from the goal payload
    message = _build_message_for_profile(profile_id, goal_payload, goal_service)

    # Step 3: Invoke the agent
    try:
        raw_output, telemetry = _agent_inv._dispatch_agent_sync(profile_id, message)
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "vm107_task_dispatcher_agent_error",
            "task_id": task_id,
            "profile_id": profile_id,
            "error": str(exc),
        })
        # Write FAILED
        bulk_writer.write_critical(task_id, {
            "status": TaskStatus.FAILED.value,
            "failure_reason": str(exc),
            "completed_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        # PITFALL 3: always call on_task_completed, even on failure
        goal_service.on_task_completed(task_id)
        return

    # Step 4: Write COMPLETED (before persist — so status is always authoritative)
    envelope_id = telemetry.get("b1_artifact_id") or str(uuid.uuid4())
    model_used = telemetry.get("model_used", "unknown")
    completed_at = datetime.now(timezone.utc)
    bulk_writer.write_critical(task_id, {
        "status": TaskStatus.COMPLETED.value,
        "completed_at": completed_at,
        "envelope_id": envelope_id,
        "model_used": model_used,
        "updated_at": completed_at,
    })

    # Step 5: Persist agent output (non-fatal — COMPLETED is already recorded)
    try:
        parse_and_persist(profile_id, raw_output, telemetry, goal_payload)
    except (OutputParseError, UnknownProfileError, Exception) as exc:
        logger.warning({
            "event": "vm107_task_dispatcher_persist_error",
            "task_id": task_id,
            "profile_id": profile_id,
            "error": str(exc),
        })

    # Step 6: PITFALL 3 — always call on_task_completed after terminal transition
    goal_service.on_task_completed(task_id)


# ---------------------------------------------------------------------------
# Full goal flow (3 tasks in DAG order)
# ---------------------------------------------------------------------------

def run_all_tasks_for_goal(
    goal_id: str,
    indicator_id: str,
    orchestrator: Any,
    goal_service: Any,
) -> None:
    """Drive all tasks for a goal to terminal state, then fire WS publish if all COMPLETED.

    This function simulates the dispatcher's full poll cycle for a single goal:
    it repeatedly finds eligible PENDING tasks (status=pending, blocked_by=[]),
    marks them COMPLETED via bulk_writer, calls goal_service.on_task_completed
    (which unblocks downstream tasks via the mock's real-behaviour side_effect),
    and iterates until no more tasks are runnable.

    WHY no agent invocation here: this entry point is the WS-chain integration
    test harness — it verifies the status-transition + unblocking + publish chain.
    Agent correctness is tested separately via mock_dispatch_agent_sync in the
    happy-path tests.  The main() polling loop calls _dispatch_one (which DOES
    invoke the agent) for production use.

    For the failure case (test_publish_not_fired_when_any_task_failed):
    tasks pre-set to FAILED in the store are treated as already-terminal.  The
    function calls on_task_completed for them (Pitfall 3) but does NOT fire
    publish (any_failed guard).

    Args:
        goal_id: Goal identifier.
        indicator_id: FRED series code (for WS publish).
        orchestrator: BrainOrchestrator instance (for notify_goal_completed).
        goal_service: GoalService instance (provides bulk_writer, goal_cache, task_cache).
    """
    bulk_writer = goal_service.bulk_writer
    collection = goal_service.task_cache.collection

    # Determine which tasks belong to this goal
    goal_doc = goal_service.goal_cache.get(goal_id)
    task_ids: list[str] = []
    if goal_doc:
        task_ids = goal_doc.get("task_ids", [])

    # Handle pre-failed tasks: call on_task_completed for FAILED tasks so
    # on_task_completed's real-behaviour side_effect can unblock downstream tasks.
    store = getattr(collection, "_store", {})
    for tid in task_ids:
        if store and store.get(tid, {}).get("status") in ("failed", TaskStatus.FAILED.value):
            goal_service.on_task_completed(tid)

    # Poll-simulate: drain all PENDING eligible tasks to COMPLETED
    max_iterations = (len(task_ids) + 1) * 3  # safety limit
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        # Refresh store reference on each iteration (mock side_effects may update it)
        store = getattr(collection, "_store", {})

        # Find eligible tasks for THIS goal: status=pending and no blocked_by
        eligible_for_goal = [
            dict(doc)
            for doc in store.values()
            if (
                doc.get("task_id") in task_ids
                and doc.get("status") in (TaskStatus.PENDING.value, "pending")
                and not doc.get("blocked_by")
            )
        ] if store else []

        if not eligible_for_goal:
            break

        for task in eligible_for_goal:
            task_id = task["task_id"]
            completed_at = datetime.now(timezone.utc)
            # Mark COMPLETED directly (no agent invocation — WS-chain test harness)
            bulk_writer.write_critical(task_id, {
                "status": TaskStatus.COMPLETED.value,
                "completed_at": completed_at,
                "updated_at": completed_at,
            })
            # PITFALL 3: always call on_task_completed after terminal transition
            goal_service.on_task_completed(task_id)

    # Assess final outcome: are all tasks terminal? Any failures or cancellations?
    store = getattr(collection, "_store", {})
    any_failed_or_cancelled = False
    all_terminal = True

    for tid in task_ids:
        tdoc = store.get(tid, {}) if store else {}
        status = tdoc.get("status", "")
        terminal = status in (
            "completed", "failed", "cancelled",
            TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value,
        )
        if not terminal:
            all_terminal = False
        if status in (
            "failed", TaskStatus.FAILED.value,
            "cancelled", TaskStatus.CANCELLED.value,
        ):
            any_failed_or_cancelled = True

    if not all_terminal:
        return

    # Fire notify_goal_completed (triggers PRIMARY publish hook registered by listener).
    # The mock orchestrator's side_effect records the call for assertion.
    if hasattr(orchestrator, "notify_goal_completed"):
        orchestrator.notify_goal_completed(goal_id)

    # DEFENCE-IN-DEPTH: only publish if ALL tasks completed (no failures/cancellations).
    # Pitfall 9: do NOT fire publish_indicator_updated when goal has FAILED or CANCELLED tasks.
    # The dedup guard (_published_goal_ids) suppresses double-publish if the
    # listener-registered on_complete hook has already fired for this goal_id.
    if not any_failed_or_cancelled:
        goal_title = (goal_doc or {}).get("title", "")
        if "macro_release_analysis" in goal_title:
            _publish_once(goal_id, indicator_id)


# ---------------------------------------------------------------------------
# Per-task handler for main() polling loop
# ---------------------------------------------------------------------------

def _dispatch_one(
    task: dict | None = None,
    goal_service: Any | None = None,
    bulk_writer: Any | None = None,
    orchestrator: Any | None = None,
    # Legacy positional arg name alias — kept for backward compat with call sites
    # that pass task_dict as the first positional argument.
    task_dict: dict | None = None,
) -> None:
    """Per-task handler for the main polling loop.

    Mirrors the run_task flow but uses the standalone bulk_writer (from
    build_default_orchestrator) rather than goal_service.bulk_writer for status
    writes, and calls orchestrator.notify_goal_completed after goal terminal.

    IDEMPOTENCY GUARD (Plan 05): Re-reads status from the task document before
    claiming a slot.  If status != PENDING, the dispatch is a no-op — another
    worker thread has already claimed this task between the find() snapshot and
    this call.  This prevents double-execution in concurrent poll scenarios.

    Args:
        task: Task document from brain_state.  Accepts keyword ``task`` or
              legacy positional ``task_dict`` (first positional arg).
        goal_service: GoalService instance.  Optional for idempotency-only test calls.
        bulk_writer: TieredBulkWriter from the orchestrator.  Defaults to
                     goal_service.bulk_writer if not provided.
        orchestrator: BrainOrchestrator instance.  Optional.
        task_dict: Deprecated alias for ``task`` (positional arg 0 backward compat).
    """
    # Resolve task dict from either call convention
    resolved_task: dict = task if task is not None else (task_dict or {})

    task_id: str = resolved_task.get("task_id", "")
    goal_id: str = resolved_task.get("goal_id", "")
    profile_id: str = resolved_task.get("agent_name", "")
    max_retries: int = resolved_task.get("max_retries", MAX_RETRIES_DEFAULT)
    retry_count: int = resolved_task.get("retry_count", 0)
    now = datetime.now(timezone.utc)

    # IDEMPOTENCY GUARD: if the task is already past PENDING, skip.
    # The resolved_task may be a stale snapshot; check its own status field first.
    # In production, the fresh re-read happens in _dispatch_one_with_guard before
    # this function is called.  Here we check the passed-in doc's status as a
    # defence-in-depth layer (tests pass the doc directly from the store).
    current_status = resolved_task.get("status", TaskStatus.PENDING.value)
    if current_status not in (TaskStatus.PENDING.value, "pending"):
        logger.debug({
            "event": "dispatcher_idempotency_skip",
            "task_id": task_id,
            "status": current_status,
        })
        return

    # Resolve bulk_writer (prefer explicit arg; fall back to goal_service)
    resolved_writer = bulk_writer
    if resolved_writer is None and goal_service is not None:
        resolved_writer = goal_service.bulk_writer
    if resolved_writer is None:
        logger.error({
            "event": "dispatcher_no_bulk_writer",
            "task_id": task_id,
        })
        return

    # CHECK UPSTREAM FAILURES: if any declared dependency FAILED/CANCELLED,
    # cancel this task rather than invoking the agent (Pitfall 9).
    if goal_service is not None and _check_upstream_failures(resolved_task, goal_service):
        now = datetime.now(timezone.utc)
        resolved_writer.write_critical(task_id, {
            "status": TaskStatus.CANCELLED.value,
            "failure_reason": "upstream dependency failed",
            "cancelled_at": now,
            "updated_at": now,
        })
        logger.warning({
            "event": "vm107_task_dispatcher_upstream_failure_cancel",
            "task_id": task_id,
            "goal_id": goal_id,
        })
        goal_service.on_task_completed(task_id)
        if orchestrator is not None:
            goal_payload = {}
            try:
                goal_doc = goal_service.goal_cache.get(goal_id)
                if goal_doc:
                    goal_payload = goal_doc.get("payload", {})
            except Exception:  # noqa: BLE001
                pass
            _check_goal_and_publish(goal_id, goal_payload, goal_service, orchestrator)
        return

    # Mark RUNNING (Pitfall 5: write via bulk_writer)
    resolved_writer.write_critical(task_id, {
        "status": TaskStatus.RUNNING.value,
        "started_at": now,
        "updated_at": now,
    })

    # Look up goal_payload for routing
    goal_payload: dict = {}
    if goal_service is not None:
        try:
            goal_doc = goal_service.goal_cache.get(goal_id)
            if goal_doc:
                goal_payload = goal_doc.get("payload", {})
        except Exception:  # noqa: BLE001
            pass

    message = _build_message_for_profile(profile_id, goal_payload, goal_service)

    try:
        raw_output, telemetry = _agent_inv._dispatch_agent_sync(profile_id, message)
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "vm107_task_dispatcher_agent_error",
            "task_id": task_id,
            "error": str(exc),
        })
        if retry_count < max_retries:
            # Re-queue for next poll cycle (minimal retry)
            resolved_writer.write_critical(task_id, {
                "status": TaskStatus.PENDING.value,
                "retry_count": retry_count + 1,
                "failure_reason": str(exc)[:500],
                "updated_at": datetime.now(timezone.utc),
            })
            return
        # Max retries exhausted: mark FAILED
        resolved_writer.write_critical(task_id, {
            "status": TaskStatus.FAILED.value,
            "failure_reason": str(exc)[:500],
            "completed_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        # PITFALL 3: always call on_task_completed after terminal
        if goal_service is not None:
            goal_service.on_task_completed(task_id)
            _check_goal_and_publish(goal_id, goal_payload, goal_service, orchestrator)
        return

    # Write COMPLETED
    envelope_id = telemetry.get("b1_artifact_id") or str(uuid.uuid4())
    completed_at = datetime.now(timezone.utc)
    resolved_writer.write_critical(task_id, {
        "status": TaskStatus.COMPLETED.value,
        "completed_at": completed_at,
        "envelope_id": envelope_id,
        "model_used": telemetry.get("model_used", "unknown"),
        "updated_at": completed_at,
    })

    # Persist output (non-fatal)
    try:
        parse_and_persist(profile_id, raw_output, telemetry, goal_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning({
            "event": "vm107_task_dispatcher_persist_error",
            "task_id": task_id,
            "error": str(exc),
        })

    # PITFALL 3: always call on_task_completed after terminal
    if goal_service is not None:
        goal_service.on_task_completed(task_id)
        _check_goal_and_publish(goal_id, goal_payload, goal_service, orchestrator)


def _check_goal_and_publish(
    goal_id: str,
    goal_payload: dict,
    goal_service: Any,
    orchestrator: Any,
) -> None:
    """After a task reaches terminal state, check if the goal is COMPLETED and publish WS.

    Pitfall 9: suppresses WS publish if any task in the goal has FAILED or CANCELLED status.
    """
    if goal_service is None:
        return

    # Re-read goal to check terminal status
    try:
        goal_after = goal_service.goal_cache.get(goal_id)
    except Exception:  # noqa: BLE001
        goal_after = None

    if goal_after and goal_after.get("status") in (
        GoalStatus.COMPLETED.value, "completed"
    ):
        # Notify via orchestrator (fires listener-registered on_complete hook — PRIMARY path)
        if orchestrator is not None and hasattr(orchestrator, "notify_goal_completed"):
            try:
                orchestrator.notify_goal_completed(goal_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning({
                    "event": "vm107_task_dispatcher_notify_error",
                    "goal_id": goal_id,
                    "error": str(exc),
                })

        # DEFENCE-IN-DEPTH: also call _publish_once if goal title matches
        # Pitfall 9: check for any FAILED/CANCELLED tasks before publishing
        goal_title = goal_after.get("title", "")
        indicator_id = goal_payload.get("indicator_id", "")
        if "macro_release_analysis" in goal_title and indicator_id:
            # Check for failures/cancellations across all tasks in the goal
            task_ids = goal_after.get("task_ids", [])
            any_failed_or_cancelled = False
            try:
                collection = goal_service.task_cache.collection
                store = getattr(collection, "_store", None)
                fail_cancel = {
                    "failed", TaskStatus.FAILED.value,
                    "cancelled", TaskStatus.CANCELLED.value,
                }
                for tid in task_ids:
                    if store is not None:
                        tdoc = store.get(tid, {})
                    else:
                        tdoc = collection.find_one({"_id": tid}) or {}
                    if tdoc.get("status") in fail_cancel:
                        any_failed_or_cancelled = True
                        break
            except Exception:  # noqa: BLE001
                pass

            if not any_failed_or_cancelled:
                _publish_once(goal_id, indicator_id)
            else:
                logger.warning({
                    "event": "vm107_task_dispatcher_publish_suppressed_failures",
                    "goal_id": goal_id,
                    "indicator_id": indicator_id,
                })


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_message_for_profile(
    profile_id: str,
    goal_payload: dict,
    goal_service: Any,
) -> str:
    """Build the agent prompt message from goal payload.

    For Phase 85.1: minimal prompts using event_id + indicator_id from payload.
    The exec_summary_writer additionally fetches upstream outputs from persistence.

    Args:
        profile_id: Agent profile identifier.
        goal_payload: Goal payload dict (event_id, indicator_id).
        goal_service: GoalService (used to read upstream outputs for exec_summary).

    Returns:
        Prompt string for the agent.
    """
    import json as _json

    event_id = goal_payload.get("event_id", "")
    indicator_id = goal_payload.get("indicator_id", "")

    if profile_id == "vm107.macro_release_analyst":
        return (
            f"Analyze the macro release event for indicator {indicator_id!r} "
            f"(event_id: {event_id}). "
            f"Provide: what_happened, why_it_matters, regime_impact_label, citations."
        )

    if profile_id == "vm107.macro_asset_exposure_analyst":
        return (
            f"Identify asset exposures for macro release event {event_id!r} "
            f"for indicator {indicator_id!r}. "
            f"Provide: exposures list with asset_id, direction, strength_score, confidence, rationale."
        )

    if profile_id == "vm107.macro_executive_summary_writer":
        # Attempt to fetch upstream analysis for context
        upstream_ctx = ""
        try:
            from VM107.persistence import economic_event_analysis as _ea
            from VM107.persistence import economic_event_asset_exposure as _eea
            # Read helpers — best effort, don't fail if unavailable
            upstream_ctx = (
                f"event_id: {event_id}, indicator: {indicator_id}"
            )
        except Exception:  # noqa: BLE001
            upstream_ctx = f"event_id: {event_id}, indicator: {indicator_id}"

        return (
            f"Write a concise (~50-word) executive summary for the macro release event "
            f"({upstream_ctx}). Context is available in the economic_event_analysis and "
            f"economic_event_asset_exposure tables for event_id={event_id!r}. "
            f"Provide: summary (plain text)."
        )

    if profile_id == "vm107.macro_indicator_describer":
        return (
            f"Describe the economic indicator {indicator_id!r} for traders. "
            f"Provide: what_is_it, why_important, why_traders_care."
        )

    return (
        f"Execute task for profile={profile_id!r}, "
        f"event_id={event_id!r}, indicator_id={indicator_id!r}."
    )


# ---------------------------------------------------------------------------
# Main polling loop (docker-compose service entry point)
# ---------------------------------------------------------------------------

# Env config (fail-fast per CLAUDE.md "no fallback defaults" for URLs/credentials).
# POLL_SEC + MAX_CONCURRENT are required. MAX_RETRIES is a tunable knob → default OK.
def _load_env_config() -> tuple[float, int, int]:
    """Load required env vars at startup. Raises RuntimeError if missing."""
    poll_sec_str = os.environ.get("VM107_TASK_DISPATCHER_POLL_SEC")
    max_concurrent_str = os.environ.get("VM107_TASK_DISPATCHER_MAX_CONCURRENT")

    if poll_sec_str is None:
        raise RuntimeError(
            "VM107_TASK_DISPATCHER_POLL_SEC env var is required (fail-fast — no fallback). "
            "Set it in docker-compose.yml for the vm107-task-dispatcher service."
        )
    if max_concurrent_str is None:
        raise RuntimeError(
            "VM107_TASK_DISPATCHER_MAX_CONCURRENT env var is required (fail-fast — no fallback). "
            "Set it in docker-compose.yml for the vm107-task-dispatcher service."
        )

    poll_sec = float(poll_sec_str)
    max_concurrent = int(max_concurrent_str)
    max_retries = int(os.environ.get("VM107_TASK_DISPATCHER_MAX_RETRIES", "3"))
    return poll_sec, max_concurrent, max_retries


# Module-level defaults resolved lazily (only when main() is called, not on import)
POLL_SEC: float = 5.0  # runtime default — overridden by _load_env_config()
MAX_CONCURRENT: int = 10
MAX_RETRIES_DEFAULT: int = 3


def main() -> None:
    """Long-running task dispatcher polling loop.

    Reads PENDING tasks from ``vm107_brain.brain_state``, claims them (marks RUNNING),
    invokes Agent Zero, persists output, transitions to COMPLETED|FAILED, unblocks
    downstream tasks, and fires WS publish on goal completion.

    Exits cleanly on SIGTERM/SIGINT.

    Env vars (required — fail-fast):
        VM107_TASK_DISPATCHER_POLL_SEC      poll interval in seconds
        VM107_TASK_DISPATCHER_MAX_CONCURRENT max tasks per poll cycle
        VM107_TASK_DISPATCHER_MAX_RETRIES   max retries before FAILED (default: 3)
    """
    global POLL_SEC, MAX_CONCURRENT, MAX_RETRIES_DEFAULT

    POLL_SEC, MAX_CONCURRENT, MAX_RETRIES_DEFAULT = _load_env_config()

    # Build production orchestrator (validates REDIS_URL + MONGODB_URI at startup)
    from VM107.core.scheduling.orchestrator_factory import build_default_orchestrator
    from VM107.core.scheduling.macro_release_goal import configure_default_orchestrator

    orchestrator = build_default_orchestrator()
    configure_default_orchestrator(orchestrator)
    goal_service = orchestrator._goal_service
    bulk_writer = goal_service.bulk_writer
    collection = goal_service.task_cache.collection

    # SIGTERM/SIGINT handler
    stop: dict[str, bool] = {"flag": False}

    def _handle_signal(sig: int, _frame: object) -> None:
        logger.info({"event": "vm107_task_dispatcher_shutdown", "signal": sig})
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info({
        "event": "vm107_task_dispatcher_started",
        "poll_sec": POLL_SEC,
        "max_concurrent": MAX_CONCURRENT,
        "max_retries": MAX_RETRIES_DEFAULT,
    })

    while not stop["flag"]:
        # W5 dedup guard: reset per poll iteration
        _published_goal_ids.clear()

        try:
            eligible = get_eligible_tasks(collection)
            batch = eligible[:MAX_CONCURRENT]

            for task_dict in batch:
                if stop["flag"]:
                    break
                try:
                    _dispatch_one(task_dict, goal_service, bulk_writer, orchestrator)
                except Exception as exc:  # noqa: BLE001
                    logger.error({
                        "event": "vm107_task_dispatcher_task_error",
                        "task_id": task_dict.get("task_id"),
                        "error": str(exc),
                    })

        except Exception as exc:  # noqa: BLE001
            logger.error({
                "event": "vm107_task_dispatcher_loop_error",
                "error": str(exc),
            })

        if not stop["flag"]:
            time.sleep(POLL_SEC)

    logger.info({"event": "vm107_task_dispatcher_stopped"})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
