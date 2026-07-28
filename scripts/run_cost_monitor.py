"""Cost/budget monitor runner — Phase 1 of the notification-pipeline wire-up.

Long-running APScheduler ``BlockingScheduler`` that periodically aggregates
AI-spend from ``fingpt_agents.agent_runs`` (via
``services.cost_monitor_aggregator.CostMonitorAggregator``) and drives the two
dormant Phase 74 detectors:

    * ``CostAnomalyDetector.evaluate(conv_type, current_hour_cost, now)``
      — per conv_type current-hour spend vs the 7-day same-hour baseline.
    * ``BudgetThresholdMonitor.evaluate(spent_today_usd, now)``
      — daily budget 80 / 100 / 120 % threshold crossings.

Both detectors publish Observations to the ``vm107.observations`` Redis channel
(``services.observation_publisher``), which VM100's notification bell consumes.
This runner is the trigger the detectors were missing — until now their inputs
were populated only by tests.

Ships as the docker-compose sibling service ``vm107-cost-monitor`` per the
``feedback_mgmt_commands_need_compose_service`` lock (Phase 74-03 cautionary
tale: a producer with no compose service silently dies on backend restart).

Run locally / inside the sibling service::

    python -m scripts.run_cost_monitor

Restart after env changes (NEVER ``docker restart`` — it ignores env_file edits)::

    docker compose up -d --force-recreate --no-deps vm107-cost-monitor

Env vars required (fail-fast; no ``os.getenv("X", "default")`` per CLAUDE.md
``env-driven-no-fallbacks`` lock). Note the detectors + publisher ALSO resolve
their own env at import time; this runner re-checks the superset up front so the
sibling-service container never silently no-ops:

    MONGODB_URI                     — fingpt_agents.agent_runs source
    VM107_SUPERVISORY_REDIS_URL     — observation_publisher Redis channel
    COST_ANOMALY_MULTIPLIER_WARN    — cost_anomaly_detector WARNING multiplier
    COST_ANOMALY_MULTIPLIER_CRITICAL— cost_anomaly_detector CRITICAL multiplier
    DAILY_AI_BUDGET_USD             — budget_threshold_monitor daily budget

Optional:

    COST_MONITOR_INTERVAL_SEC       — tick cadence in seconds (default 300)
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Where the healthcheck reads the last-successful-tick timestamp. ``/app/logs``
# is the canonical container path; the compose service mounts host ``./logs``.
LAST_RUN_FILE = pathlib.Path("/app/logs/cost_monitor_last_run.iso")

# Default tick cadence — 5 minutes. Cost anomalies are hourly-granularity
# signals; 5-min polling gives timely bell alerts without hammering Mongo.
_DEFAULT_INTERVAL_SEC = 300

_MONGO_DB = "fingpt_agents"


def _env_required(key: str) -> str:
    """Return env var value or exit(1). No fallback defaults."""
    value = os.environ.get(key)
    if not value:
        sys.stderr.write(
            f"ERROR: env var {key} required (CLAUDE.md "
            "env-driven-no-fallbacks lock — no default)\n"
        )
        sys.exit(1)
    return value


class _LoggingTierDownRouter:
    """Minimal router satisfying ``BudgetThresholdMonitor``'s 120% tier-down call.

    ``BudgetThresholdMonitor.evaluate`` invokes ``router.tier_down_for_overage``
    at the 120 % threshold BEFORE publishing its Observation, so the router must
    never raise (else the budget CRITICAL bell alert would be lost). The full
    ``core.routing.ModelRouter`` tier-down (which downgrades non-trade-path
    conv-types to cheaper models) is a separate model-routing concern, out of
    scope for this notification wire-up phase. Here we log the overage so the
    signal is observable; wiring the real router is a follow-up.
    """

    def tier_down_for_overage(self, conv_types) -> None:  # noqa: ANN001
        logger.warning(
            {
                "event": "cost_monitor_budget_tier_down_requested",
                "conv_types": sorted(conv_types),
                "note": (
                    "logging-only router — real ModelRouter tier-down deferred "
                    "to routing-integration phase"
                ),
            }
        )


def _build_mongo_client():
    """Construct a pymongo client from ``MONGODB_URI`` (telemetry/cost.py idiom)."""
    from pymongo import MongoClient

    mongo_uri = _env_required("MONGODB_URI")
    return MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)


def _build_context():
    """Wire the aggregator + both detectors against real collaborators.

    Imports happen INSIDE the function so the test suite (which never calls
    ``main``) does not import heavy modules, and so the env fail-fast messages
    surface before any collaborator construction.
    """
    from core.boundary.cost_calculator import CostCalculator
    from core.boundary.budget_tracker import MongoBudgetTracker
    from services.cost_monitor_aggregator import CostMonitorAggregator, CONV_TYPES
    from services.cost_anomaly_detector import CostAnomalyDetector
    from services.budget_threshold_monitor import BudgetThresholdMonitor

    mongo_uri = _env_required("MONGODB_URI")
    client = _build_mongo_client()
    agent_runs = client[_MONGO_DB]["agent_runs"]

    # Preferred spent-today source (Phase 41 budget_usage); aggregator falls back
    # to summing agent_runs if this read fails at tick time.
    budget_tracker = MongoBudgetTracker(mongo_uri, database=_MONGO_DB)

    calc = CostCalculator()
    aggregator = CostMonitorAggregator(agent_runs, budget_tracker=budget_tracker)
    cost_detector = CostAnomalyDetector(calc)
    budget_monitor = BudgetThresholdMonitor(router=_LoggingTierDownRouter())

    return {
        "aggregator": aggregator,
        "calc": calc,
        "cost_detector": cost_detector,
        "budget_monitor": budget_monitor,
        "conv_types": CONV_TYPES,
    }


def _record_last_run() -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(tz=timezone.utc).isoformat())


def run_once(ctx: dict) -> dict:
    """Execute one aggregate → evaluate cycle. Returns a stats dict.

    Steps:
      1. aggregate current-hour spend + spent-today + plumb the 7-day baseline
         into the CostCalculator ledger (closes the test-only gap).
      2. for each conv_type, call ``cost_detector.evaluate``.
      3. call ``budget_monitor.evaluate`` once with spent-today.

    Observations (if any thresholds cross) are published by the detectors to the
    ``vm107.observations`` Redis channel as a side effect.
    """
    now = datetime.now(tz=timezone.utc)

    aggregator = ctx["aggregator"]
    calc = ctx["calc"]
    cost_detector = ctx["cost_detector"]
    budget_monitor = ctx["budget_monitor"]
    conv_types = ctx["conv_types"]

    # Aggregate + plumb the baseline into the calculator ledger for THIS tick.
    snap = aggregator.populate_calculator_ledger(calc, now)

    cost_observations = 0
    for conv_type in conv_types:
        current_hour_cost = snap.current_hour_costs.get(conv_type, 0.0)
        obs = cost_detector.evaluate(conv_type, current_hour_cost, now)
        if obs is not None:
            cost_observations += 1

    budget_obs = budget_monitor.evaluate(snap.spent_today_usd, now)
    budget_observations = 1 if budget_obs is not None else 0

    stats = {
        "event": "cost_monitor_tick",
        "now": now.isoformat(),
        "spent_today_usd": round(snap.spent_today_usd, 4),
        "current_hour_total_usd": round(sum(snap.current_hour_costs.values()), 4),
        "ledger_rows": len(snap.ledger_rows),
        "cost_observations_emitted": cost_observations,
        "budget_observations_emitted": budget_observations,
        "observations_emitted": cost_observations + budget_observations,
    }
    return stats


def _run_tick(ctx: dict) -> None:
    """Execute one tick, write the heartbeat, log the stats. Never raise."""
    try:
        stats = run_once(ctx)
        _record_last_run()
        logger.info(stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception({"event": "cost_monitor_tick_failed", "error": str(exc)})


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Fail-fast on the full required env superset BEFORE wiring collaborators.
    # (The detectors + publisher also fail-fast at import; we front-run them so
    #  the operator sees a clean message rather than an import traceback.)
    _env_required("MONGODB_URI")
    _env_required("VM107_SUPERVISORY_REDIS_URL")
    _env_required("COST_ANOMALY_MULTIPLIER_WARN")
    _env_required("COST_ANOMALY_MULTIPLIER_CRITICAL")
    _env_required("DAILY_AI_BUDGET_USD")

    interval_sec = int(os.environ.get("COST_MONITOR_INTERVAL_SEC", _DEFAULT_INTERVAL_SEC))

    from apscheduler.schedulers.blocking import BlockingScheduler

    ctx = _build_context()
    sched = BlockingScheduler(timezone="UTC")

    sched.add_job(
        _run_tick,
        trigger="interval",
        seconds=interval_sec,
        kwargs={"ctx": ctx},
        id="cost_monitor_tick",
        max_instances=1,
        coalesce=True,
    )

    # Immediate first tick so the healthcheck has a valid heartbeat before the
    # interval fires (avoids the sibling service flapping unhealthy on boot).
    logger.info({"event": "cost_monitor_starting", "interval_sec": interval_sec})
    _run_tick(ctx)

    sched.start()


if __name__ == "__main__":  # pragma: no cover — exercised by the sibling service
    main()
