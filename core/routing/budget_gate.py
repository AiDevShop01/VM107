"""
BudgetGate — Redis-backed per-goal budget enforcement at routing time.

Per-goal hard daily budget gate (Step 2 of router pipeline).

Reads aggregates from Redis on every call. On cache miss, reads MongoDB ONCE per goal-per-day.
On 100% breach: writes force_local + enqueue_blocked to MongoDB; scheduler honors via Phase 42.

Anti-patterns (CONTEXT.md): NEVER query MongoDB per call. Cache miss is the only Mongo touch.

budget_caps (Plan 02 model_routing.yaml -> budget_caps block) is config for the agent_type and
system scope max_usd values used by Plan 05's multi-scope alert evaluation. Per-goal max lives
on the goal document and is unaffected by this kwarg.

Redis key schema (LOCKED — all keys use HSET with 25h TTL):
    router:budget:goal:{goal_id}     → {date, spent_usd, max_usd, status, force_local, enqueue_blocked}
    router:budget:agent:{agent_type} → {date, spent_usd}
    router:budget:system             → {date, spent_usd}

TTL = 90000s (25h: calendar midnight + 1h safety margin for late-finishing tasks).

100% breach behavior (LOCKED per CONTEXT.md):
    - Router: force_local_only = True (immediately, this call)
    - Scheduler: enqueue_blocked = True for that goal (no new tasks queued)
    - Running tasks: complete normally on local models (drain-down)
    - P1 critical tasks: BYPASS the enqueue block (recovery, ingestion, safety)
    - Goal state in Mongo: {budget_status: "exceeded", enqueue_blocked: true, force_local: true}
    - Auto-resume when budget resets (calendar midnight — no human intervention by default)

Fail-open on Redis errors: if Redis is unavailable, allow routing to proceed
(agent must not be blocked by infrastructure failures).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, date as date_cls
from typing import Any, Optional


# Redis key templates (LOCKED from Plan 01 SUMMARY)
REDIS_KEY_GOAL = "router:budget:goal:{goal_id}"
REDIS_KEY_AGENT = "router:budget:agent:{agent_type}"
REDIS_KEY_SYSTEM = "router:budget:system"
REDIS_TTL_SECONDS = 90000   # 25h: covers midnight + 1h safety


def _today_iso() -> str:
    """Return today's date as ISO string (YYYY-MM-DD)."""
    return date_cls.today().isoformat()


class BudgetGate:
    """
    Redis-backed budget enforcement gate.

    Called as Step 2 of the routing pipeline. Returns (allow, reason) tuple.
    If not allowed, router returns local-only chain without running steps 3-7.

    budget_caps shape: {"agent_types": {<agent_id>: {"max_usd_per_day": float}},
                        "system": {"max_usd_per_day": float}}

    Injected at construction by Plan 05's ModelRouter.from_yaml() passing
    affinity.budget_caps so the aggregate getters can return max_usd values.
    """

    def __init__(
        self,
        redis_client: Any,
        mongo_client: Any,
        logger: logging.Logger | None = None,
        budget_caps: Optional[dict] = None,
    ) -> None:
        """
        Initialize BudgetGate.

        Args:
            redis_client: Synchronous redis-py client (reuses Phase 42 pattern)
            mongo_client: MongoDB client for goal state writes on breach
            logger: Optional logger override
            budget_caps: Optional dict from AffinityMap.budget_caps (Plan 02).
                         Used by get_agent_type_aggregate/get_system_aggregate for max_usd.
                         None is treated as empty dict (no caps configured = max_usd=0.0).
        """
        self.redis = redis_client
        self.mongo = mongo_client
        self.log = logger or logging.getLogger("router.budget_gate")
        self.budget_caps = budget_caps or {"agent_types": {}, "system": {}}

    # ---- Hot path ----

    def check(self, goal_id: str, priority: str = "P3") -> tuple[bool, str]:
        """
        Check if goal budget allows this routing call.

        Hot path: single Redis hgetall. On cache miss reads MongoDB ONCE per goal-per-day.
        P1 tasks bypass enqueue_blocked (but still get force_local routing if budget exceeded).

        Returns:
            (True, "budget_ok")             — within budget
            (True, "no_budget_set")         — goal has no budget constraint
            (True, "unknown_goal")          — no record found — fail-open
            (True, "redis_unavailable")     — Redis error — fail-open
            (True, "p1_bypass_force_local") — P1 bypasses block (caller sees force_local)
            (False, "budget_exceeded")      — non-P1 at 100%+ budget
        """
        key = REDIS_KEY_GOAL.format(goal_id=goal_id)
        try:
            data = self._hgetall_str(key)
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "budget_gate_redis_error",
                "goal_id": goal_id,
                "error": str(e),
            }))
            return (True, "redis_unavailable")  # fail-open

        if not data:
            # Cache miss: warm from Mongo once, re-evaluate
            warmed = self._warm_from_mongo(goal_id)
            if warmed is None:
                return (True, "unknown_goal")     # no record = unconstrained
            if warmed.get("max_usd") is None or warmed["max_usd"] == float("inf"):
                return (True, "no_budget_set")
            data = {
                "spent_usd": str(warmed["spent_usd"]),
                "max_usd": str(warmed["max_usd"]),
                "status": warmed.get("status", "ok"),
            }

        spent = float(data.get("spent_usd", 0.0))
        max_usd_raw = data.get("max_usd", "inf")
        max_usd = float("inf") if max_usd_raw == "inf" else float(max_usd_raw)
        status = data.get("status", "ok")

        # P1 bypass: critical tasks bypass enqueue_blocked but still get force_local routing
        if status == "exceeded":
            if priority == "P1":
                return (True, "p1_bypass_force_local")
            return (False, "budget_exceeded")

        if max_usd > 0 and spent >= max_usd:
            # First call observing breach — record it
            self.record_breach(goal_id)
            if priority == "P1":
                return (True, "p1_bypass_force_local")
            return (False, "budget_exceeded")

        return (True, "budget_ok")

    # ---- Cache warm ----

    def _warm_from_mongo(self, goal_id: str) -> Optional[dict]:
        """
        Read goal from Mongo ONCE, compute today's spend, warm Redis.

        Returns the cached dict with keys {spent_usd, max_usd, status} (float values)
        or None if goal not found.
        """
        try:
            doc = self.mongo.fingpt_agents.agent_goals.find_one({"goal_id": goal_id})
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "budget_gate_mongo_error",
                "goal_id": goal_id,
                "error": str(e),
            }))
            return None

        if doc is None:
            return None

        max_usd = doc.get("budget_max_cost_usd")
        spent_today = float(doc.get("budget_spent_today") or 0.0)
        status = doc.get("budget_status") or "ok"

        cached = {
            "date": _today_iso(),
            "spent_usd": str(spent_today),
            "max_usd": "inf" if max_usd is None else str(max_usd),
            "status": status,
            "force_local": "1" if doc.get("force_local") else "0",
            "enqueue_blocked": "1" if doc.get("enqueue_blocked") else "0",
        }
        try:
            key = REDIS_KEY_GOAL.format(goal_id=goal_id)
            self.redis.hset(key, mapping=cached)
            self.redis.expire(key, REDIS_TTL_SECONDS)
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "budget_gate_redis_warm_error",
                "goal_id": goal_id,
                "error": str(e),
            }))

        # Return as float values for evaluation
        return {
            "spent_usd": spent_today,
            "max_usd": max_usd if max_usd is not None else float("inf"),
            "status": status,
        }

    # ---- State transitions (write-through Redis + Mongo) ----

    def record_breach(self, goal_id: str) -> None:
        """
        100% breach: set force_local + enqueue_blocked + status=exceeded in Redis AND Mongo.

        Writes to MongoDB agent_goals collection (fields added by migration 005):
            {budget_status: "exceeded", enqueue_blocked: True, force_local: True,
             budget_breach_at: <now>}

        Also updates Redis key status to "exceeded".
        """
        now = datetime.now(timezone.utc)
        redis_updates = {
            "status": "exceeded",
            "force_local": "1",
            "enqueue_blocked": "1",
        }
        mongo_updates = {
            "budget_status": "exceeded",
            "force_local": True,
            "enqueue_blocked": True,
            "budget_breach_at": now,
        }
        self._dual_write(goal_id, redis_updates, mongo_updates)
        self.log.warning(json.dumps({
            "event": "budget_breach_recorded",
            "goal_id": goal_id,
            "breach_at": now.isoformat(),
        }))

    def record_warning(self, goal_id: str, threshold_pct: float) -> None:
        """
        Record budget warning at threshold_pct (50% or 80%).

        Updates budget_status field WITHOUT blocking (no force_local change).
        Plan 04 alert pipeline calls this at 50% and 80% thresholds.
        """
        if threshold_pct >= 0.8:
            status = "warning_80"
        elif threshold_pct >= 0.5:
            status = "warning_50"
        else:
            return
        redis_updates = {"status": status}
        mongo_updates = {"budget_status": status}
        self._dual_write(goal_id, redis_updates, mongo_updates)
        self.log.info(json.dumps({
            "event": "budget_warning_recorded",
            "goal_id": goal_id,
            "status": status,
        }))

    def auto_resume_check(self, goal_id: str) -> None:
        """
        Check if a previously breached goal should resume (budget reset at midnight).

        Called by scheduler on each tick for goals with enqueue_blocked=True.
        If Redis key date has rolled over (new calendar day), clears breach state:
            - Redis key: reset spent_usd=0, status="ok", force_local="0", enqueue_blocked="0"
            - MongoDB: enqueue_blocked=False, force_local=False, budget_status="ok",
                       budget_spent_today=0.0

        No human intervention required for auto-resume (CONTEXT.md locked).
        """
        key = REDIS_KEY_GOAL.format(goal_id=goal_id)
        data = self._hgetall_str(key)
        cached_date = data.get("date")
        today = _today_iso()

        if cached_date is None or cached_date == today:
            return  # Still same day — no reset needed

        # Date rolled over → reset all breach state
        redis_updates = {
            "date": today,
            "spent_usd": "0.0",
            "status": "ok",
            "force_local": "0",
            "enqueue_blocked": "0",
        }
        mongo_updates = {
            "budget_status": "ok",
            "force_local": False,
            "enqueue_blocked": False,
            "budget_spent_today": 0.0,
        }
        self._dual_write(goal_id, redis_updates, mongo_updates)
        self.log.info(json.dumps({
            "event": "budget_auto_resume",
            "goal_id": goal_id,
            "reset_date": today,
        }))

    def increment_spend(self, goal_id: str, agent_type: str, cost_usd: float) -> dict:
        """
        Post-call: bump spent_usd in goal+agent+system Redis aggregates AND Mongo.

        Uses HINCRBYFLOAT for atomic Redis increments across all three scopes:
            - router:budget:goal:{goal_id}
            - router:budget:agent:{agent_type}
            - router:budget:system

        Also writes $inc to MongoDB budget_spent_today for goal document.

        Returns updated goal aggregate (hgetall of the goal key after increment).
        """
        try:
            # Redis goal aggregate (only when a goal context exists)
            if goal_id:
                gkey = REDIS_KEY_GOAL.format(goal_id=goal_id)
                self.redis.hincrbyfloat(gkey, "spent_usd", cost_usd)
                self.redis.expire(gkey, REDIS_TTL_SECONDS)

            # Redis agent_type aggregate (always — applies to UI calls too)
            akey = REDIS_KEY_AGENT.format(agent_type=agent_type)
            self.redis.hincrbyfloat(akey, "spent_usd", cost_usd)
            self.redis.hset(akey, mapping={"date": _today_iso()})
            self.redis.expire(akey, REDIS_TTL_SECONDS)

            # Redis system aggregate (always)
            self.redis.hincrbyfloat(REDIS_KEY_SYSTEM, "spent_usd", cost_usd)
            self.redis.hset(REDIS_KEY_SYSTEM, mapping={"date": _today_iso()})
            self.redis.expire(REDIS_KEY_SYSTEM, REDIS_TTL_SECONDS)
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "increment_spend_redis_error",
                "goal_id": goal_id,
                "error": str(e),
            }))

        # Mongo write-through (only when goal context exists — else there's no doc to update)
        if goal_id:
            try:
                self.mongo.fingpt_agents.agent_goals.update_one(
                    {"goal_id": goal_id},
                    {"$inc": {"budget_spent_today": cost_usd}},
                )
            except Exception as e:
                self.log.warning(json.dumps({
                    "event": "increment_spend_mongo_error",
                    "goal_id": goal_id,
                    "error": str(e),
                }))

        return self._hgetall_str(REDIS_KEY_GOAL.format(goal_id=goal_id)) if goal_id else {}

    # ---- Aggregate getters (consumed by Plan 05's multi-scope alert evaluation) ----

    def get_agent_type_aggregate(self, agent_id: str) -> dict:
        """
        Returns {"spent_usd": float, "max_usd": float} for the agent_type scope.

        spent_usd: Redis HGETALL on router:budget:agent:{agent_id}.
        max_usd: self.budget_caps['agent_types'][agent_id]['max_usd_per_day'] (0.0 if not configured).

        Plan 05 callers: if max_usd <= 0, skip alert evaluation for this scope (no cap).
        Fail-open on Redis errors (returns spent_usd=0.0).
        """
        spent = 0.0
        try:
            data = self._hgetall_str(REDIS_KEY_AGENT.format(agent_type=agent_id))
            spent = float(data.get("spent_usd", 0.0))
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "agent_aggregate_redis_error",
                "agent_id": agent_id,
                "error": str(e),
            }))

        cap_block = self.budget_caps.get("agent_types", {}).get(agent_id) or {}
        max_usd = float(cap_block.get("max_usd_per_day", 0.0))
        return {"spent_usd": spent, "max_usd": max_usd}

    def get_system_aggregate(self) -> dict:
        """
        Returns {"spent_usd": float, "max_usd": float} for the system-wide scope.

        spent_usd: Redis HGETALL on router:budget:system.
        max_usd: self.budget_caps['system']['max_usd_per_day'] (0.0 if not configured).

        Plan 05 callers: if max_usd <= 0, skip alert evaluation for this scope (no cap).
        Fail-open on Redis errors.
        """
        spent = 0.0
        try:
            data = self._hgetall_str(REDIS_KEY_SYSTEM)
            spent = float(data.get("spent_usd", 0.0))
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "system_aggregate_redis_error",
                "error": str(e),
            }))

        sys_block = self.budget_caps.get("system") or {}
        max_usd = float(sys_block.get("max_usd_per_day", 0.0))
        return {"spent_usd": spent, "max_usd": max_usd}

    # ---- Internal helpers ----

    def _dual_write(self, goal_id: str, redis_updates: dict, mongo_updates: dict) -> None:
        """Write updates to both Redis and MongoDB. Errors are logged but not raised."""
        try:
            key = REDIS_KEY_GOAL.format(goal_id=goal_id)
            self.redis.hset(key, mapping=redis_updates)
            self.redis.expire(key, REDIS_TTL_SECONDS)
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "dual_write_redis_error",
                "goal_id": goal_id,
                "error": str(e),
            }))
        try:
            self.mongo.fingpt_agents.agent_goals.update_one(
                {"goal_id": goal_id},
                {"$set": mongo_updates},
            )
        except Exception as e:
            self.log.warning(json.dumps({
                "event": "dual_write_mongo_error",
                "goal_id": goal_id,
                "error": str(e),
            }))

    def _hgetall_str(self, key: str) -> dict:
        """Call redis.hgetall and decode bytes keys/values to str."""
        raw = self.redis.hgetall(key)
        if not raw:
            return {}
        out = {}
        for k, v in raw.items():
            ks = k.decode() if isinstance(k, bytes) else k
            vs = v.decode() if isinstance(v, bytes) else v
            out[ks] = vs
        return out
