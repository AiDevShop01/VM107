"""
BudgetGate — Redis-backed per-goal budget enforcement at routing time.

Enforces hard daily spend limits per goal before model selection proceeds.
Redis is the read path (never MongoDB per call — explicit CONTEXT.md anti-pattern).

Redis key schema (LOCKED — all keys use HSET with 25h TTL):
    router:budget:goal:{goal_id}     → {date, spent_usd, max_usd, status}
    router:budget:agent:{agent_type} → {date, spent_usd}
    router:budget:system             → {date, spent_usd}

TTL = 25h (calendar midnight + 1h safety margin for late-finishing tasks).

100% breach behavior (LOCKED per CONTEXT.md):
    - Router: force_local_only = True (immediately, this call)
    - Scheduler: enqueue_blocked = True for that goal (no new tasks queued)
    - Running tasks: complete normally on local models (drain-down)
    - P1 critical tasks: BYPASS the enqueue block (recovery, ingestion, safety)
    - Goal state in Mongo: {budget_status: "exceeded", enqueue_blocked: true, force_local: true}
    - Auto-resume when budget resets (calendar midnight — no human intervention by default)

Fail-open on Redis errors: if Redis is unavailable, allow routing to proceed
(agent must not be blocked by infrastructure failures).

Implementation plan: Plan 03 replaces stubs with real Redis reads + breach logic.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("router.budget_gate")


class BudgetGate:
    """
    Redis-backed budget enforcement gate.

    Called as Step 2 of the routing pipeline. Returns (ok, reason) tuple.
    If not ok, router returns local-only chain without running steps 3-7.

    Redis key schema (documented for Plan 03 executor):
        Key: router:budget:goal:{goal_id}
        Type: HSET
        Fields: date (YYYY-MM-DD), spent_usd (float), max_usd (float), status (str)
        TTL: 25h (set on creation, refreshed on each update)

        Key: router:budget:agent:{agent_type}
        Type: HSET
        Fields: date (YYYY-MM-DD), spent_usd (float)
        TTL: 25h

        Key: router:budget:system
        Type: HSET
        Fields: date (YYYY-MM-DD), spent_usd (float)
        TTL: 25h

    All methods raise NotImplementedError until Plan 03 implements them.
    """

    def __init__(
        self,
        redis_client: Any,
        mongo_client: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize BudgetGate.

        Args:
            redis_client: Synchronous redis-py client (reuses Phase 42 pattern)
            mongo_client: MongoDB client for goal state writes on breach
            logger: Optional logger override
        """
        self.redis = redis_client
        self.mongo = mongo_client
        self._logger = logger or globals()["logger"]

    def check(self, goal_id: str, priority: str) -> tuple[bool, str]:
        """
        Check if goal budget allows this routing call.

        Reads Redis aggregate key. Cache miss: queries MongoDB once to initialize
        Redis key (only on first call per goal per day).

        P1 tasks: bypass enqueue_blocked check (but not force_local — P1 still
        routes to local if budget exceeded, it just doesn't get blocked from queuing).

        Args:
            goal_id: Goal identifier
            priority: Task priority ("P1", "P2", "P3", "P4")

        Returns:
            (True, "ok") if budget allows, (False, reason) if blocked.
            reason is one of: "exceeded_force_local", "goal_not_found", "redis_error".

        Raises:
            NotImplementedError: Until Plan 03 implements real Redis read.
        """
        raise NotImplementedError("Phase 43 Plan 03: BudgetGate.check() pending")

    def record_breach(self, goal_id: str) -> None:
        """
        Record 100% budget breach: write force_local+enqueue_blocked to MongoDB goal.

        Writes to MongoDB agent_goals collection (fields added by migration 005):
            {budget_status: "exceeded", enqueue_blocked: true, force_local: true,
             budget_breach_at: <now>}

        Also updates Redis key status to "exceeded".

        Args:
            goal_id: Goal that breached budget

        Raises:
            NotImplementedError: Until Plan 03 implements breach handler.
        """
        raise NotImplementedError("Phase 43 Plan 03: BudgetGate.record_breach() pending")

    def record_warning(self, goal_id: str, threshold_pct: float) -> None:
        """
        Record budget warning at threshold_pct (50% or 80%).

        Updates MongoDB goal budget_status field:
            50% -> budget_status: "warning_50"
            80% -> budget_status: "warning_80"

        Also updates Redis key status field.

        Args:
            goal_id: Goal approaching budget limit
            threshold_pct: Threshold crossed (0.5 for 50%, 0.8 for 80%)

        Raises:
            NotImplementedError: Until Plan 03 implements warning handler.
        """
        raise NotImplementedError("Phase 43 Plan 03: BudgetGate.record_warning() pending")

    def auto_resume_check(self, goal_id: str) -> None:
        """
        Check if a previously breached goal should resume (budget reset at midnight).

        Called by scheduler on each tick for goals with enqueue_blocked=True.
        If Redis key date has rolled over (new calendar day), clears breach state:
            - Redis key: reset spent_usd=0, status="ok"
            - MongoDB: enqueue_blocked=False, force_local=False, budget_status="ok",
                       budget_spent_today=0.0

        No human intervention required for auto-resume (CONTEXT.md locked).

        Args:
            goal_id: Goal to check for budget reset

        Raises:
            NotImplementedError: Until Plan 03 implements auto-resume logic.
        """
        raise NotImplementedError("Phase 43 Plan 03: BudgetGate.auto_resume_check() pending")
