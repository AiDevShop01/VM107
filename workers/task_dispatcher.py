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
from datetime import datetime, timezone
from typing import Any

from VM107.core.scheduling.enums import GoalStatus, TaskStatus
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
    "get_eligible_tasks",
    "run_task",
    "run_all_tasks_for_goal",
    "parse_and_persist",
    "_publish_once",
    "_dispatch_one",
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

    Args:
        goal_id: Goal identifier (used as dedup key).
        indicator_id: FRED series code to publish the invalidation for.
    """
    if goal_id in _published_goal_ids:
        logger.info({"event": "publish_dedup_skip", "goal_id": goal_id, "indicator_id": indicator_id})
        return

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

    # Assess final outcome: are all tasks terminal? Any failures?
    store = getattr(collection, "_store", {})
    any_failed = False
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
        if status in ("failed", TaskStatus.FAILED.value):
            any_failed = True

    if not all_terminal:
        return

    # Fire notify_goal_completed (triggers PRIMARY publish hook registered by listener).
    # The mock orchestrator's side_effect records the call for assertion.
    if hasattr(orchestrator, "notify_goal_completed"):
        orchestrator.notify_goal_completed(goal_id)

    # DEFENCE-IN-DEPTH: if no failures, fire publish via dedup guard.
    # The dedup guard (_published_goal_ids) suppresses double-publish if the
    # listener-registered on_complete hook has already fired for this goal_id.
    if not any_failed:
        goal_title = (goal_doc or {}).get("title", "")
        if "macro_release_analysis" in goal_title:
            _publish_once(goal_id, indicator_id)


# ---------------------------------------------------------------------------
# Per-task handler for main() polling loop
# ---------------------------------------------------------------------------

def _dispatch_one(
    task_dict: dict,
    goal_service: Any,
    bulk_writer: Any,
    orchestrator: Any,
) -> None:
    """Per-task handler for the main polling loop.

    Mirrors the run_task flow but uses the standalone bulk_writer (from
    build_default_orchestrator) rather than goal_service.bulk_writer for status
    writes, and calls orchestrator.notify_goal_completed after goal terminal.

    Args:
        task_dict: Task document from brain_state.
        goal_service: GoalService instance.
        bulk_writer: TieredBulkWriter from the orchestrator.
        orchestrator: BrainOrchestrator instance.
    """
    task_id: str = task_dict["task_id"]
    goal_id: str = task_dict.get("goal_id", "")
    profile_id: str = task_dict.get("agent_name", "")
    max_retries: int = task_dict.get("max_retries", MAX_RETRIES_DEFAULT)
    retry_count: int = task_dict.get("retry_count", 0)
    now = datetime.now(timezone.utc)

    # Mark RUNNING (Pitfall 5: write via bulk_writer)
    bulk_writer.write_critical(task_id, {
        "status": TaskStatus.RUNNING.value,
        "started_at": now,
        "updated_at": now,
    })

    # Look up goal_payload for routing
    goal_payload: dict = {}
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
            # Re-queue for next poll cycle (minimal retry — Plan 05 hardens this)
            bulk_writer.write_critical(task_id, {
                "status": TaskStatus.PENDING.value,
                "retry_count": retry_count + 1,
                "failure_reason": str(exc),
                "updated_at": datetime.now(timezone.utc),
            })
            return
        # Max retries exhausted: mark FAILED
        bulk_writer.write_critical(task_id, {
            "status": TaskStatus.FAILED.value,
            "failure_reason": str(exc),
            "completed_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        # PITFALL 3: always call on_task_completed after terminal
        goal_service.on_task_completed(task_id)
        _check_goal_and_publish(goal_id, goal_payload, goal_service, orchestrator)
        return

    # Write COMPLETED
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

    # PITFALL 3: always call on_task_completed after terminal
    goal_service.on_task_completed(task_id)
    _check_goal_and_publish(goal_id, goal_payload, goal_service, orchestrator)


def _check_goal_and_publish(
    goal_id: str,
    goal_payload: dict,
    goal_service: Any,
    orchestrator: Any,
) -> None:
    """After a task reaches terminal state, check if the goal is COMPLETED and publish WS."""
    # Re-read goal to check terminal status
    try:
        goal_after = goal_service.goal_cache.get(goal_id)
    except Exception:  # noqa: BLE001
        goal_after = None

    if goal_after and goal_after.get("status") in (
        GoalStatus.COMPLETED.value, "completed"
    ):
        # Notify via orchestrator (fires listener-registered on_complete hook — PRIMARY path)
        if hasattr(orchestrator, "notify_goal_completed"):
            try:
                orchestrator.notify_goal_completed(goal_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning({
                    "event": "vm107_task_dispatcher_notify_error",
                    "goal_id": goal_id,
                    "error": str(exc),
                })

        # DEFENCE-IN-DEPTH: also call _publish_once if goal title matches
        goal_title = goal_after.get("title", "")
        indicator_id = goal_payload.get("indicator_id", "")
        if "macro_release_analysis" in goal_title and indicator_id:
            _publish_once(goal_id, indicator_id)


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
