"""Brain goal wrapper for macro release analysis (Phase 85 Plan 10).

Provides ``create_macro_release_goal(event_id, indicator_id)`` — the single
public function callers use. On each new macro release event it:

  1. Creates a ``macro_release_analysis`` goal via the BrainOrchestrator.
  2. Fans out 3 child tasks with the correct DAG edges:
       task1: vm107.macro_release_analyst          (no deps — runs immediately)
       task2: vm107.macro_asset_exposure_analyst   (no deps — runs immediately, parallel)
       task3: vm107.macro_executive_summary_writer (depends on task1 + task2)
  3. Dispatches the goal so the scheduler picks it up.

Idempotent: if a goal already exists for (event_id), returns the existing
goal_id without creating duplicate tasks.

Completion-hook approach chosen: Approach B (Brain emits goal-completion event,
subscriber wires the WS publish). BrainOrchestrator does NOT have an on_complete
callback; Plan 85-11 listens for goal.name == "macro_release_analysis" completion.
See Phase 85 Plan 10 SUMMARY for full decision rationale.

Brain API reality: GoalService (core.scheduling.goal_service) provides
create_goal/task lifecycle; BrainLayer (core.scheduling.brain) is the
deterministic policy controller. BrainOrchestrator (defined below) is a thin
adapter that wraps GoalService with the simpler create_goal/add_task/dispatch
interface that Phase 85 agents consume. This avoids callers constructing
GoalService's full dependency graph (MongoDB, Redis, etc.) directly.

Env-driven config: no URLs or credentials hardcoded here. Callers supply
either a concrete BrainOrchestrator instance or override via ``orchestrator=``.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BrainOrchestrator protocol (structural typing)
# ---------------------------------------------------------------------------

class BrainOrchestratorProtocol(Protocol):
    """Structural protocol for the Brain orchestrator interface.

    Implemented by BrainOrchestrator (real) and any mock (tests).
    """

    def find_goal_by_event_id(self, event_id: str) -> str | None:
        """Return existing goal_id if one was already created for event_id, else None."""
        ...

    def create_goal(self, *, name: str, payload: dict[str, Any]) -> str:
        """Create a new goal and return its goal_id."""
        ...

    def add_task(self, goal_id: str, *, profile_id: str, depends_on: list[str]) -> str:
        """Add a task to goal_id and return the new task_id."""
        ...

    def dispatch(self, goal_id: str) -> None:
        """Signal the scheduler to begin executing the goal."""
        ...


# ---------------------------------------------------------------------------
# BrainOrchestrator — production adapter over GoalService
# ---------------------------------------------------------------------------

class BrainOrchestrator:
    """Thin adapter wrapping GoalService with the simplified Phase 85 API.

    Production callers build this from GoalService + TaskService instances.
    Tests replace it with MagicMock (matching BrainOrchestratorProtocol).

    Why not instantiate GoalService directly?
    GoalService requires MongoCachedCollection, TieredBulkWriter, RedisPriorityQueue,
    DecompositionEngine, GovernanceMatrix, and DAGValidator — a deep dependency
    graph that cannot be satisfied without a running MongoDB + Redis. BrainOrchestrator
    collapses this complexity behind the 4-method interface above.
    """

    def __init__(self, goal_service, task_service=None, event_goal_index: dict | None = None):
        """
        Args:
            goal_service: GoalService instance (core.scheduling.goal_service.GoalService)
            task_service:  Optional task creation helper (may be None if GoalService
                           handles tasks internally via decomposition).
            event_goal_index: Optional shared dict mapping event_id → goal_id for
                              idempotency checks. If None, a fresh in-process dict is used
                              (only safe within a single process lifetime).
        """
        self._goal_service = goal_service
        self._task_service = task_service
        self._event_goal_index: dict[str, str] = event_goal_index if event_goal_index is not None else {}

    def find_goal_by_event_id(self, event_id: str) -> str | None:
        return self._event_goal_index.get(event_id)

    def create_goal(self, *, name: str, payload: dict[str, Any]) -> str:
        """Create a GoalService goal and return its goal_id.

        Uses GoalType.EXECUTION with Priority.P2 (macro analysis is high-value
        but not P1 operational-critical).
        """
        from core.scheduling.models import GoalCreateRequest
        from core.scheduling.enums import GoalType, Priority

        request = GoalCreateRequest(
            title=f"{name}: {payload.get('indicator_id', 'unknown')}",
            description=(
                f"Macro release analysis for event_id={payload.get('event_id', 'unknown')}, "
                f"indicator={payload.get('indicator_id', 'unknown')}"
            ),
            goal_type=GoalType.EXECUTION,
            priority=Priority.P2,
            created_by="vm107.macro_release_event_listener",
            objective_label="macro_intelligence",
        )
        goal = self._goal_service.create_goal(request, creator="vm107.macro_release_event_listener")
        # Track for idempotency
        event_id = payload.get("event_id", "")
        if event_id:
            self._event_goal_index[event_id] = goal.goal_id
        return goal.goal_id

    def add_task(self, goal_id: str, *, profile_id: str, depends_on: list[str]) -> str:
        """Add a task to a goal and return the task_id.

        Delegates to GoalService's task tracking (or task_service if provided).
        task_type is set to 'analysis' for all macro agents.
        """
        import uuid
        from datetime import datetime, timezone
        from core.scheduling.enums import Priority, TaskStatus

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        task_dict = {
            "task_id": task_id,
            "goal_id": goal_id,
            "task_type": "analysis",
            "status": TaskStatus.PENDING.value if not depends_on else TaskStatus.BLOCKED.value,
            "priority": Priority.P2.value,
            "dependencies": depends_on,
            "blocked_by": depends_on,
            "preemptible": False,
            "retry_count": 0,
            "max_retries": 3,
            "agent_name": profile_id,
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }

        # Write task via GoalService bulk_writer (or task_service if provided)
        if self._task_service is not None:
            self._task_service.create_task(task_dict)
        elif hasattr(self._goal_service, 'bulk_writer') and self._goal_service.bulk_writer is not None:
            self._goal_service.bulk_writer.write_critical(task_id, task_dict)

        return task_id

    def dispatch(self, goal_id: str) -> None:
        """Activate the goal so the scheduler begins executing ready tasks."""
        try:
            self._goal_service.activate_goal(goal_id)
            logger.info({"event": "macro_release_goal_dispatched", "goal_id": goal_id})
        except Exception as exc:
            # Log but don't re-raise — goal may already be active
            logger.warning({
                "event": "macro_release_goal_dispatch_warning",
                "goal_id": goal_id,
                "error": str(exc),
            })


# ---------------------------------------------------------------------------
# Module-level singleton orchestrator (lazy-initialized for production)
# ---------------------------------------------------------------------------

_default_orchestrator: BrainOrchestratorProtocol | None = None


def _get_default_orchestrator() -> BrainOrchestratorProtocol:
    """Return the module-level orchestrator (initialized on first call).

    This is intentionally NOT initialized at module import time — doing so
    would require MongoDB + Redis connections on startup which violates the
    fail-fast principle (should fail only when actually needed, not on import).
    """
    global _default_orchestrator
    if _default_orchestrator is None:
        # Lazy import: avoid pulling in database infrastructure at module load time
        raise RuntimeError(
            "No default BrainOrchestrator configured. "
            "Call create_macro_release_goal(orchestrator=...) with a concrete instance, "
            "or call configure_default_orchestrator() during application startup."
        )
    return _default_orchestrator


def configure_default_orchestrator(orchestrator: BrainOrchestratorProtocol) -> None:
    """Set the module-level default orchestrator (call during application startup).

    Args:
        orchestrator: A BrainOrchestrator (or any object matching the protocol).
    """
    global _default_orchestrator
    _default_orchestrator = orchestrator
    logger.info({"event": "macro_release_goal_orchestrator_configured"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_macro_release_goal(
    event_id: str,
    indicator_id: str,
    *,
    orchestrator: BrainOrchestratorProtocol | None = None,
) -> str:
    """Create a macro_release_analysis goal with 3 child tasks.

    DAG structure:
        task1 (macro_release_analyst)         — no deps; runs immediately
        task2 (macro_asset_exposure_analyst)  — no deps; runs in parallel with task1
        task3 (macro_executive_summary_writer) — depends on task1 + task2; runs after both

    Idempotent: if a goal for (event_id) already exists, returns the existing
    goal_id without creating duplicate tasks or dispatching again.

    Args:
        event_id:     Unique identifier for this release event.
                      Callers derived from payload as ``f"{indicator_id}:{release_timestamp}"``.
        indicator_id: FRED series code (e.g. "CPIAUCSL").
        orchestrator: BrainOrchestrator instance. If None, uses the module-level
                      default (configure_default_orchestrator must have been called).

    Returns:
        str: goal_id of the created (or existing) goal.
    """
    orc = orchestrator if orchestrator is not None else _get_default_orchestrator()

    # --- Idempotency check ---
    existing_goal_id = orc.find_goal_by_event_id(event_id)
    if existing_goal_id is not None:
        logger.info({
            "event": "macro_release_goal_idempotent",
            "event_id": event_id,
            "goal_id": existing_goal_id,
        })
        return existing_goal_id

    # --- Create the goal ---
    goal_id = orc.create_goal(
        name="macro_release_analysis",
        payload={"event_id": event_id, "indicator_id": indicator_id},
    )
    logger.info({
        "event": "macro_release_goal_created",
        "event_id": event_id,
        "indicator_id": indicator_id,
        "goal_id": goal_id,
    })

    # --- Add 3 tasks in DAG order ---
    # task1 + task2 run in parallel (no dependencies)
    task1_id = orc.add_task(
        goal_id,
        profile_id="vm107.macro_release_analyst",
        depends_on=[],
    )
    task2_id = orc.add_task(
        goal_id,
        profile_id="vm107.macro_asset_exposure_analyst",
        depends_on=[],
    )
    # task3 runs after both task1 and task2 complete
    orc.add_task(
        goal_id,
        profile_id="vm107.macro_executive_summary_writer",
        depends_on=[task1_id, task2_id],
    )

    # --- Dispatch: scheduler picks up ready tasks ---
    orc.dispatch(goal_id)
    logger.info({
        "event": "macro_release_goal_dispatched",
        "goal_id": goal_id,
        "task1": task1_id,
        "task2": task2_id,
    })

    return goal_id
