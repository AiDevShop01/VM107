"""
AlertPipeline — multi-threshold, multi-sink, multi-scope cost alerting.

Evaluates budget thresholds and fans out alerts to configured sinks.
Part of the "event → persistence → intelligence → action → escalation" control loop.

Thresholds (all enabled, LOCKED per CONTEXT.md):
    50%  — informational warning (stdout JSON + MongoDB only; no action signal)
    80%  — actionable warning (all sinks except external; emits Brain cost_pressure signal)
    100% — hard breach (all 4 sinks fire; triggers force_local + enqueue_blocked)

Four sinks (LOCKED per CONTEXT.md, evaluated after every cost-incurring call):
    stdout:       Structured JSON log (mandatory, every threshold)
    mongodb:      router_alerts collection (mandatory, every threshold)
    brain_signal: cost_pressure Signal to SignalAccumulator (80% and 100% only)
    external:     Notification (Slack/Discord/email — 100% ONLY, to avoid alert fatigue)

Three scopes (all evaluated independently after each cost-incurring call):
    goal:       Per-goal daily spend vs max_budget_usd (primary control unit)
    agent_type: Per-agent-type aggregate (pattern detection)
    system:     System-wide daily total (global safety net)

Per-goal custom threshold overrides supported via alert_overrides in model_routing.yaml:
    alert_overrides:
      "goal-execution-001": {warn_pct: 0.75, critical_pct: 0.9}

Implementation plan: Plan 04 replaces stubs with real threshold evaluation + sink fan-out.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.routing.schemas import AlertEvent

logger = logging.getLogger("router.alert_pipeline")


class AlertPipeline:
    """
    Multi-threshold, multi-sink budget alert fan-out engine.

    Called after every cost-incurring LLM call (from chat_model_call_after extension)
    to evaluate whether any budget scope has crossed a threshold.

    Sink implementations (LOCKED):
    1. stdout JSON:   json.dumps(alert_event.model_dump()) + logger.info()  — always
    2. MongoDB:       router_alerts collection insert  — always
    3. Brain signal:  SignalAccumulator.emit_signal(Signal(type="cost_pressure", ...))  — 80%+
    4. External:      External notifier call (Slack/Discord/email)  — 100% only

    Anti-pattern: External alerts at 50%/80% → alert fatigue → ignored system.
    Anti-pattern: Single-sink alerting → each observability/control layer needs its own sink.

    All methods raise NotImplementedError until Plan 04 implements them.
    """

    def __init__(
        self,
        mongo_client: Any,
        signal_accumulator: Any,
        external_notifier: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize AlertPipeline.

        Args:
            mongo_client: MongoDB client for router_alerts writes
            signal_accumulator: Phase 42 SignalAccumulator for cost_pressure signals
            external_notifier: Optional external notification handler (100% breaches only).
                               None disables external notifications gracefully.
            logger: Optional logger override
        """
        self.mongo = mongo_client
        self.signal_accumulator = signal_accumulator
        self.external_notifier = external_notifier
        self._logger = logger or globals()["logger"]

    def evaluate(
        self,
        scope: str,
        goal_id_or_agent_type: str,
        spent: float,
        max_usd: float,
        custom_overrides: Optional[dict] = None,
    ) -> list[AlertEvent]:
        """
        Evaluate budget thresholds and return list of AlertEvents to fire.

        Evaluates all three threshold levels (50%, 80%, 100%) against the current
        spend percentage. Only thresholds that have been newly crossed are returned
        (prevents duplicate alerts on subsequent calls).

        Custom overrides from alert_overrides YAML block allow per-goal threshold
        customization (e.g. execution goals warn at 75%, research at 90%).

        Args:
            scope: Alert scope ("goal", "agent_type", "system")
            goal_id_or_agent_type: Identifier for the scope (goal_id or agent_type name)
            spent: Amount spent today in USD
            max_usd: Budget ceiling in USD
            custom_overrides: Optional per-scope threshold overrides dict
                             {warn_pct: float, critical_pct: float}

        Returns:
            List of AlertEvent objects to be fired via fire(). Empty list if no
            thresholds crossed.

        Raises:
            NotImplementedError: Until Plan 04 implements threshold evaluation.
        """
        raise NotImplementedError("Phase 43 Plan 04: AlertPipeline.evaluate() pending")

    def fire(self, event: AlertEvent) -> None:
        """
        Fan out a single AlertEvent to all configured sinks.

        Sink order (each fires independently — failure in one doesn't block others):
        1. stdout JSON log (always)
        2. MongoDB router_alerts insert (always)
        3. Brain cost_pressure signal (80% and 100% thresholds only)
        4. External notification (100% threshold only)

        sinks_fired field on event is updated to record which sinks succeeded.

        Args:
            event: AlertEvent to fan out

        Raises:
            NotImplementedError: Until Plan 04 implements sink fan-out.
        """
        raise NotImplementedError("Phase 43 Plan 04: AlertPipeline.fire() pending")
