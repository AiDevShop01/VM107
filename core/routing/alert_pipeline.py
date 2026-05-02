"""
AlertPipeline — deterministic multi-sink, multi-threshold, multi-scope cost alerting.

Sink matrix (LOCKED per CONTEXT.md ROUTER-ALERTS-01):
    50%  → stdout JSON + MongoDB router_alerts
    80%  → stdout JSON + MongoDB router_alerts + Brain cost_pressure signal
    100% → stdout JSON + MongoDB router_alerts + Brain cost_pressure signal + external notification

Scope matrix (all evaluated independently after every cost-incurring call):
    goal:       Per-goal daily spend vs max_budget_usd (primary control unit)
    agent_type: Per-agent-type aggregate (pattern detection)
    system:     System-wide daily total (global safety net)

Per-goal custom threshold overrides supported via alert_overrides in model_routing.yaml:
    alert_overrides:
      "goal-execution-001": {warn_pct: 0.75, critical_pct: 0.9}

Anti-patterns (explicitly rejected per CONTEXT.md):
    - External alerts at 50%/80%: alert fatigue → ignored system
    - Single-sink alerting: each observability/control layer needs its own sink
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from core.routing.schemas import AlertEvent

logger = logging.getLogger("router.alert_pipeline")

# Default threshold percentages (LOCKED per CONTEXT.md)
DEFAULT_WARN_PCT = 0.5      # 50% — informational
DEFAULT_ACTION_PCT = 0.8    # 80% — actionable
DEFAULT_BREACH_PCT = 1.0    # 100% — hard breach


class ExternalNotifier:
    """
    Stub interface for external notifications (Slack/Discord/email).

    Concrete adapters land in Phase 44+. For now this logs to stdout via
    the module logger so that 100% breach events leave a visible trace without
    requiring external configuration.

    This stub is pluggable — pass a concrete notifier to AlertPipeline.__init__
    once a real adapter exists.
    """

    def notify(self, event: AlertEvent) -> None:
        """Send external notification for a 100% budget breach event."""
        logging.getLogger("router.external_notifier").info(json.dumps({
            "event": "external_notify_stub",
            "alert": event.model_dump(mode="json"),
        }))


class AlertPipeline:
    """
    Multi-threshold, multi-sink budget alert fan-out engine.

    Called after every cost-incurring LLM call (via chat_model_call_after extension)
    to evaluate whether any budget scope has crossed a threshold.

    Sink order on fire() (each fires independently — failure in one does not block others):
    1. stdout JSON log (always, every threshold)
    2. MongoDB router_alerts collection insert (always, every threshold)
    3. Brain cost_pressure signal via SignalAccumulator (80%+ only)
    4. External notification via ExternalNotifier (100% only, anti-fatigue rule)

    Usage (Plan 05 post-call hook):
        events = pipeline.evaluate_and_fire("goal", goal_id, spent, max_usd)
        events += pipeline.evaluate_and_fire("agent_type", agent_type, spent, max_usd)
        events += pipeline.evaluate_and_fire("system", None, system_spent, system_max)
    """

    def __init__(
        self,
        mongo_client: Any,
        signal_accumulator: Any,
        external_notifier: Optional[ExternalNotifier] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize AlertPipeline.

        Args:
            mongo_client: MongoDB client for router_alerts writes
                          (write path: mongo.fingpt_agents.router_alerts.insert_one)
            signal_accumulator: Phase 42 SignalAccumulator for cost_pressure signals
            external_notifier: Optional external notification handler (100% breaches only).
                               Defaults to ExternalNotifier stub (logs to stdout).
            logger: Optional logger override (defaults to router.alert_pipeline)
        """
        self.mongo = mongo_client
        self.signal_accumulator = signal_accumulator
        self.external_notifier = external_notifier or ExternalNotifier()
        self.log = logger or globals()["logger"]

    def evaluate(
        self,
        scope: str,
        identifier: Optional[str],
        spent: float,
        max_usd: float,
        custom_overrides: Optional[dict] = None,
    ) -> list[AlertEvent]:
        """
        Evaluate budget thresholds and return the highest crossed AlertEvent.

        Returns at most one AlertEvent per call (the highest threshold crossed).
        Caller is responsible for deduplication via the goal's budget_status field
        in MongoDB — evaluate() always returns the current highest threshold.

        Custom overrides from alert_overrides YAML block allow per-goal threshold
        customization (e.g. execution goals warn at 75%, research at 90%). The
        canonical threshold label (50pct/80pct/100pct) is preserved regardless of
        the actual trigger percentage.

        Args:
            scope: Alert scope — "goal", "agent_type", or "system"
            identifier: Scope identifier — goal_id for "goal", agent_type name for
                        "agent_type", None for "system"
            spent: Amount spent today in USD
            max_usd: Budget ceiling in USD (0 or inf means no budget set → no events)
            custom_overrides: Optional per-scope threshold overrides:
                              {warn_pct: float, critical_pct: float, breach_pct: float}

        Returns:
            List with 0 or 1 AlertEvent. Empty list if no threshold crossed or if
            no budget is configured (max_usd == 0 or max_usd == inf).
        """
        # Guard: no budget configured means no alerting
        if max_usd <= 0 or max_usd == float("inf"):
            return []

        pct = spent / max_usd
        overrides = custom_overrides or {}
        warn_at = overrides.get("warn_pct", DEFAULT_WARN_PCT)
        action_at = overrides.get("critical_pct", DEFAULT_ACTION_PCT)
        breach_at = overrides.get("breach_pct", DEFAULT_BREACH_PCT)

        # Determine the highest crossed threshold (single event per evaluation)
        if pct >= breach_at:
            threshold = "100pct"
        elif pct >= action_at:
            threshold = "80pct"
        elif pct >= warn_at:
            threshold = "50pct"
        else:
            return []

        event = AlertEvent(
            scope=scope,  # type: ignore[arg-type]
            threshold=threshold,  # type: ignore[arg-type]
            goal_id=identifier if scope == "goal" else None,
            agent_type=identifier if scope == "agent_type" else None,
            spent_usd=float(spent),
            max_usd=float(max_usd),
            pct=float(pct),
            sinks_fired=[],  # populated by fire()
            created_at=datetime.now(timezone.utc),
        )
        return [event]

    def fire(self, event: AlertEvent) -> AlertEvent:
        """
        Fan out a single AlertEvent to all configured sinks.

        Sinks fire independently — failure in one sink does not prevent others.
        Returns a new AlertEvent with sinks_fired populated.

        Sink order (LOCKED per CONTEXT.md):
        1. stdout JSON log (always — every threshold)
        2. MongoDB router_alerts insert (always — every threshold)
        3. Brain cost_pressure signal (80% and 100% thresholds only)
        4. External notification (100% threshold only — anti-fatigue rule)

        Args:
            event: AlertEvent to fan out (sinks_fired must be empty on input)

        Returns:
            New AlertEvent with sinks_fired populated (original is not mutated).
        """
        sinks: list[str] = []

        # Sink 1: stdout JSON (always)
        try:
            self.log.info(json.dumps({
                "event": "router_alert",
                **event.model_dump(mode="json"),
            }))
            sinks.append("stdout")
        except Exception as exc:
            self.log.error(f"stdout sink failed: {exc}")

        # Sink 2: MongoDB router_alerts (always)
        try:
            import uuid as _uuid
            self.mongo.fingpt_agents.router_alerts.insert_one(
                {
                    "_id": str(_uuid.uuid4()),
                    **event.model_dump(mode="python"),
                }
            )
            sinks.append("mongo")
        except Exception as exc:
            self.log.warning(json.dumps({
                "event": "alert_mongo_error",
                "error": str(exc),
            }))

        # Sink 3: Brain cost_pressure signal (80%+ only)
        if event.threshold in ("80pct", "100pct"):
            try:
                self._emit_cost_pressure_signal(event)
                sinks.append("brain_signal")
            except Exception as exc:
                self.log.warning(json.dumps({
                    "event": "alert_signal_error",
                    "error": str(exc),
                }))

        # Sink 4: External notification (100% only — anti-fatigue rule)
        if event.threshold == "100pct":
            try:
                self.external_notifier.notify(event)
                sinks.append("external")
            except Exception as exc:
                self.log.warning(json.dumps({
                    "event": "alert_external_error",
                    "error": str(exc),
                }))

        return event.model_copy(update={"sinks_fired": sinks})

    def evaluate_and_fire(
        self,
        scope: str,
        identifier: Optional[str],
        spent: float,
        max_usd: float,
        custom_overrides: Optional[dict] = None,
    ) -> list[AlertEvent]:
        """
        Convenience wrapper: evaluate then immediately fire each event.

        Plan 05's post-call hook calls this for all three scopes independently:
            events  = pipeline.evaluate_and_fire("goal", goal_id, spent, max_usd)
            events += pipeline.evaluate_and_fire("agent_type", agent_type, a_spent, a_max)
            events += pipeline.evaluate_and_fire("system", None, s_spent, s_max)

        Returns fired events (with sinks_fired populated). Empty list if below all
        thresholds or if budget is unconstrained.
        """
        events = self.evaluate(scope, identifier, spent, max_usd, custom_overrides)
        return [self.fire(e) for e in events]

    def _emit_cost_pressure_signal(self, event: AlertEvent) -> None:
        """
        Emit cost_pressure signal to Brain's SignalAccumulator.

        Brain reads accumulated signals on the next update_cycle() call.
        This is a ONE-WAY channel — router never reads back from Brain.

        Signal payload shape (LOCKED per CONTEXT.md):
            {scope, budget_pct, threshold, spent_usd, max_usd}
        source = goal_id | agent_type | "system" (whichever is non-None)
        confidence = 1.0 (deterministic, not probabilistic)
        """
        from core.scheduling.signals import Signal

        source = event.goal_id or event.agent_type or "system"
        self.signal_accumulator.emit_signal(Signal(
            type="cost_pressure",
            source=source,
            payload={
                "scope": event.scope,
                "budget_pct": event.pct,
                "threshold": event.threshold,
                "spent_usd": event.spent_usd,
                "max_usd": event.max_usd,
            },
            timestamp=time.time(),
            confidence=1.0,
        ))
