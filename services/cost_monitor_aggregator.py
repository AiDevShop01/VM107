"""Cost-monitor aggregator — plumbs MongoDB AI-spend into the Phase 74 detectors.

Phase 1 of the notification-pipeline wire-up (2026-07). The dormant
``CostAnomalyDetector`` / ``BudgetThresholdMonitor`` detectors read their inputs
from an in-memory ``CostCalculator._cost_ledger`` that, until now, was populated
ONLY by tests. This module closes that gap: it reads the real
``fingpt_agents.agent_runs`` collection and produces, for a given ``now``:

    1. ``current_hour_costs``  — {conv_type: USD spent this clock-hour}
    2. ``spent_today_usd``     — total USD since UTC midnight
    3. ``ledger_rows``         — the 7-day same-hour baseline rows in the exact
                                 shape ``CostCalculator.rolling_7d_avg_same_hour``
                                 expects (one row per preceding calendar day per
                                 conv_type, ``{conv_type, hour, date, cost_usd}``).

The aggregation approach mirrors ``api/v1/telemetry/cost.py::_build_snapshot``
(pull a bounded window once, filter in-memory). All timestamps are UTC.

Timezone lock (project note ``project_lake_timestamps_tz_naive``): pymongo
returns naive-UTC datetimes by default; comparing them against tz-aware bounds
raises ``TypeError`` that broad excepts swallow as false "no-data". Every
datetime is normalised to naive-UTC before comparison here.

ADDITIVE — this module does NOT modify detector logic. It only supplies the
inputs the detectors already expect.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

log = logging.getLogger("services.cost_monitor_aggregator")

# The six hyphenated conversation types (matches telemetry/cost.py _CONV_TYPES
# and cost_anomaly_detector._CONV_TYPE_DISPLAY keys).
CONV_TYPES: tuple[str, ...] = (
    "pre-trade", "macro", "execution", "reflection", "research", "strategy",
)

# Baseline window length — must match CostCalculator.rolling_7d_avg_same_hour,
# which needs >= 7 same-hour data points before it leaves cold-start.
_BASELINE_DAYS = 7


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise any datetime to naive-UTC for comparison against Mongo dates."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@dataclass
class CostMonitorSnapshot:
    """One tick's worth of detector inputs, computed from a single Mongo read."""

    now: datetime
    current_hour_costs: dict[str, float]
    spent_today_usd: float
    ledger_rows: list[dict[str, Any]] = field(default_factory=list)


class CostMonitorAggregator:
    """Reads ``fingpt_agents.agent_runs`` and shapes it for the Phase 74 detectors.

    Parameters
    ----------
    agent_runs:
        A pymongo collection handle for ``fingpt_agents.agent_runs`` (or any
        object exposing a ``.find(filter, projection=...)`` returning dicts with
        ``cost_usd``, ``created_at`` and ``conversation_type``).
    budget_tracker:
        Optional object with ``get_daily_total() -> float`` (e.g.
        ``MongoBudgetTracker``). When provided it is the preferred source for
        ``spent_today_usd``; otherwise today's spend is summed from
        ``agent_runs``.
    conv_types:
        The conversation types to aggregate (defaults to the six hyphenated
        types).
    """

    def __init__(
        self,
        agent_runs: Any,
        budget_tracker: Optional[Any] = None,
        conv_types: Iterable[str] = CONV_TYPES,
    ) -> None:
        self._runs = agent_runs
        self._budget_tracker = budget_tracker
        self._conv_types = tuple(conv_types)

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def collect(self, now: Optional[datetime] = None) -> CostMonitorSnapshot:
        """Compute all detector inputs for ``now`` from a single Mongo read.

        Parameters
        ----------
        now:
            Reference UTC datetime. Defaults to ``datetime.now(timezone.utc)``.
            Always pass explicitly in tests for determinism.

        Returns
        -------
        CostMonitorSnapshot
            ``current_hour_costs`` (per conv_type), ``spent_today_usd`` and
            ``ledger_rows`` (7-day same-hour baseline rows).
        """
        now = now or datetime.now(timezone.utc)
        now_naive = _to_naive_utc(now)

        # Window covers the 7 preceding calendar days plus today, so a single
        # read feeds both the current-hour and the baseline computations.
        window_start = datetime(
            now_naive.year, now_naive.month, now_naive.day
        ) - timedelta(days=_BASELINE_DAYS)

        docs = self._fetch(window_start)

        current_hour_costs = self._current_hour_costs(now_naive, docs)
        ledger_rows = self._ledger_rows(now_naive, docs)
        spent_today = self._spent_today_usd(now_naive, docs)

        return CostMonitorSnapshot(
            now=now,
            current_hour_costs=current_hour_costs,
            spent_today_usd=spent_today,
            ledger_rows=ledger_rows,
        )

    def populate_calculator_ledger(
        self, calc: Any, now: Optional[datetime] = None
    ) -> CostMonitorSnapshot:
        """Compute a snapshot and assign its ledger rows to ``calc._cost_ledger``.

        This is the exact plumbing the detector expects: after this call,
        ``calc.rolling_7d_avg_same_hour(conv_type, now)`` returns a real
        7-day same-hour baseline instead of the test-only sentinel.
        """
        snap = self.collect(now)
        calc._cost_ledger = snap.ledger_rows
        return snap

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch(self, window_start_naive: datetime) -> list[dict[str, Any]]:
        """Pull the bounded window of agent_runs once (mirrors telemetry/cost.py)."""
        cursor = self._runs.find(
            {"created_at": {"$gte": window_start_naive}},
            projection={
                "_id": 0,
                "cost_usd": 1,
                "created_at": 1,
                "conversation_type": 1,
            },
        )
        return list(cursor)

    @staticmethod
    def _cost(doc: dict[str, Any]) -> float:
        return float(doc.get("cost_usd") or 0.0)

    def _current_hour_costs(
        self, now_naive: datetime, docs: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Sum spend per conv_type for the current clock-hour window."""
        hour_start = now_naive.replace(minute=0, second=0, microsecond=0)
        out: dict[str, float] = {ct: 0.0 for ct in self._conv_types}
        for d in docs:
            ts = d.get("created_at")
            if not ts:
                continue
            ts = _to_naive_utc(ts)
            if ts < hour_start or ts > now_naive:
                continue
            ct = d.get("conversation_type")
            if ct in out:
                out[ct] += self._cost(d)
        return {ct: round(v, 6) for ct, v in out.items()}

    def _ledger_rows(
        self, now_naive: datetime, docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build 7-day same-hour baseline rows in CostCalculator._cost_ledger shape.

        One row per (conv_type, preceding-calendar-day) at ``now`` hour. Days with
        no spend contribute a ``0.0`` row so every conv_type reaches the 7 data
        points ``rolling_7d_avg_same_hour`` requires to leave cold-start (a real
        $0 baseline day, not a missing sample).
        """
        target_hour = now_naive.hour
        target_date = now_naive.date()
        # The 7 preceding calendar days: [target-7, target-1] inclusive.
        window_dates = [target_date - timedelta(days=n) for n in range(1, _BASELINE_DAYS + 1)]
        window_date_set = set(window_dates)

        # (conv_type, date) -> summed cost at target_hour
        buckets: dict[tuple[str, date], float] = defaultdict(float)
        for d in docs:
            ts = d.get("created_at")
            if not ts:
                continue
            ts = _to_naive_utc(ts)
            if ts.hour != target_hour:
                continue
            ct = d.get("conversation_type")
            if ct not in self._conv_types:
                continue
            ts_date = ts.date()
            if ts_date not in window_date_set:
                continue
            buckets[(ct, ts_date)] += self._cost(d)

        rows: list[dict[str, Any]] = []
        for ct in self._conv_types:
            for d_date in window_dates:
                rows.append(
                    {
                        "conv_type": ct,
                        "hour": target_hour,
                        "date": d_date,
                        "cost_usd": round(buckets.get((ct, d_date), 0.0), 6),
                    }
                )
        return rows

    def _spent_today_usd(
        self, now_naive: datetime, docs: list[dict[str, Any]]
    ) -> float:
        """Total USD spent since UTC midnight.

        Prefers ``budget_tracker.get_daily_total()`` (Phase 41 budget_usage
        source); falls back to summing today's ``agent_runs``.
        """
        if self._budget_tracker is not None:
            try:
                return round(float(self._budget_tracker.get_daily_total()), 6)
            except Exception as exc:  # noqa: BLE001 — fall back, never crash the tick
                log.warning(
                    "cost_monitor.budget_tracker_failed, "
                    "falling back to agent_runs sum: %s",
                    exc,
                )

        today_start = now_naive.replace(hour=0, minute=0, second=0, microsecond=0)
        total = 0.0
        for d in docs:
            ts = d.get("created_at")
            if not ts:
                continue
            ts = _to_naive_utc(ts)
            if ts >= today_start:
                total += self._cost(d)
        return round(total, 6)
