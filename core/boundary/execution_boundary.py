"""
Execution boundary enforcement.

Enforces all 5 limits (steps, tokens, cost, time, daily budget) on agent execution.
"""
import json
import logging
import time
from datetime import datetime

from core.execution_context import BoundaryStatus, ExecutionContext
from core.boundary.config_resolver import ResolvedBoundaryConfig
from core.boundary.budget_tracker import BudgetTrackerInterface


logger = logging.getLogger(__name__)


class ExecutionBoundary:
    """
    Real execution boundary enforcement.

    Checks all 5 limits on every boundary check:
    1. Step limit (max_steps)
    2. Token limit (max_tokens)
    3. Cost limit (max_cost_usd)
    4. Time limit (max_execution_time_sec)
    5. Daily budget (daily_budget_usd)

    Returns specific status for each violation type.
    Logs WARNING at 80% threshold (once per limit per task).
    """

    def __init__(
        self,
        config: ResolvedBoundaryConfig,
        budget_tracker: BudgetTrackerInterface,
        agent_name: str,
    ):
        """
        Initialize execution boundary.

        Args:
            config: Resolved boundary configuration with all limits
            budget_tracker: Budget tracker for daily spend
            agent_name: Name of agent for budget tracking
        """
        self._config = config
        self._budget_tracker = budget_tracker
        self._agent_name = agent_name

        # Pre-calculate 80% warning thresholds
        self._warn_steps = int(config.max_steps * 0.8)
        self._warn_tokens = int(config.max_tokens * 0.8)
        self._warn_cost = config.max_cost_usd * 0.8
        self._warn_time = int(config.max_execution_time_sec * 0.8)
        self._warn_daily_budget = config.daily_budget_usd * 0.8

        # Track which warnings have been logged (once per limit per task)
        self._warning_logged: set[str] = set()

    async def check(self, context: ExecutionContext) -> BoundaryStatus:
        """
        Check execution boundaries.

        Check order (first violation found is returned):
        1. Steps
        2. Tokens
        3. Cost
        4. Time
        5. Daily budget

        Returns:
            BoundaryStatus.OK if all within limits
            BoundaryStatus.WARNING if any at 80% threshold
            BoundaryStatus.*_EXCEEDED if specific limit exceeded
        """
        warning = False

        # 1. Check steps
        if context.step_count >= self._config.max_steps:
            self._log_violation(
                violation_type="step_limit_exceeded",
                context=context,
                current=context.step_count,
                limit=self._config.max_steps,
            )
            return BoundaryStatus.STEP_LIMIT_EXCEEDED
        elif context.step_count >= self._warn_steps:
            self._log_warning("steps", context.step_count, self._config.max_steps)
            warning = True

        # 2. Check tokens
        if context.token_count >= self._config.max_tokens:
            self._log_violation(
                violation_type="token_limit_exceeded",
                context=context,
                current=context.token_count,
                limit=self._config.max_tokens,
            )
            return BoundaryStatus.TOKEN_LIMIT_EXCEEDED
        elif context.token_count >= self._warn_tokens:
            self._log_warning("tokens", context.token_count, self._config.max_tokens)
            warning = True

        # 3. Check cost
        if context.cost_usd >= self._config.max_cost_usd:
            self._log_violation(
                violation_type="cost_limit_exceeded",
                context=context,
                current=context.cost_usd,
                limit=self._config.max_cost_usd,
            )
            return BoundaryStatus.COST_LIMIT_EXCEEDED
        elif context.cost_usd >= self._warn_cost:
            self._log_warning("cost_usd", context.cost_usd, self._config.max_cost_usd)
            warning = True

        # 4. Check time
        elapsed = time.time() - context.start_time
        if elapsed >= self._config.max_execution_time_sec:
            self._log_violation(
                violation_type="time_limit_exceeded",
                context=context,
                current=elapsed,
                limit=self._config.max_execution_time_sec,
            )
            return BoundaryStatus.TIME_LIMIT_EXCEEDED
        elif elapsed >= self._warn_time:
            self._log_warning("execution_time_sec", elapsed, self._config.max_execution_time_sec)
            warning = True

        # 5. Check daily budget
        daily_total = self._budget_tracker.get_daily_total()
        if daily_total >= self._config.daily_budget_usd:
            self._log_violation(
                violation_type="daily_budget_exceeded",
                context=context,
                current=daily_total,
                limit=self._config.daily_budget_usd,
            )
            return BoundaryStatus.DAILY_BUDGET_EXCEEDED
        elif daily_total >= self._warn_daily_budget:
            self._log_warning("daily_budget_usd", daily_total, self._config.daily_budget_usd)
            warning = True

        return BoundaryStatus.WARNING if warning else BoundaryStatus.OK

    def _log_violation(
        self,
        violation_type: str,
        context: ExecutionContext,
        **extra,
    ) -> None:
        """
        Log boundary violation as structured JSON.

        Args:
            violation_type: Type of violation (e.g., "step_limit_exceeded")
            context: Execution context
            **extra: Additional fields (current, limit, etc.)
        """
        log_entry = {
            "event": "execution_boundary_violation",
            "violation_type": violation_type,
            "task_id": context.task_id,
            "agent_name": self._agent_name,
            "timestamp": datetime.now().astimezone().isoformat().replace("+00:00", "Z"),
            **extra,
        }
        logger.error(json.dumps(log_entry))

    def _log_warning(self, limit_name: str, current: float, max_value: float) -> None:
        """
        Log 80% warning (once per limit per task).

        Args:
            limit_name: Name of limit (e.g., "steps", "tokens")
            current: Current value
            max_value: Maximum allowed value
        """
        # Only log each warning once per task
        if limit_name in self._warning_logged:
            return

        self._warning_logged.add(limit_name)

        percent = (current / max_value) * 100
        log_entry = {
            "event": "execution_boundary_warning",
            "limit_name": limit_name,
            "current": current,
            "limit": max_value,
            "percent": round(percent, 1),
            "agent_name": self._agent_name,
            "timestamp": datetime.now().astimezone().isoformat().replace("+00:00", "Z"),
        }
        logger.warning(json.dumps(log_entry))
