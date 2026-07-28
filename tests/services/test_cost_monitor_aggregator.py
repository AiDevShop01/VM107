"""CostMonitorAggregator tests — Phase 1 notification-pipeline wire-up.

Proves the aggregator, given a fake ``agent_runs`` collection, returns:
  * per-conv-type current-hour spend,
  * spent-today (preferring the budget_tracker, falling back to agent_runs),
  * 7-day same-hour baseline rows in the exact ``CostCalculator._cost_ledger``
    shape, such that ``rolling_7d_avg_same_hour`` leaves cold-start and returns
    the real mean.

No live Mongo — a tiny in-memory fake mimics ``collection.find(filter,
projection=...)`` with a ``$gte`` on ``created_at``.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

# Aggregator itself imports no env-gated module, but keep parity with the other
# suites so a shared import order never surprises us.
os.environ.setdefault("VM107_SUPERVISORY_REDIS_URL", "redis://localhost:6379/3")

from services.cost_monitor_aggregator import (  # noqa: E402
    CONV_TYPES,
    CostMonitorAggregator,
)
from core.boundary.cost_calculator import CostCalculator  # noqa: E402


_NOW = datetime(2026, 6, 10, 14, 30, 0, tzinfo=timezone.utc)  # 14:30 UTC


class _FakeAgentRuns:
    """Minimal stand-in for a pymongo collection supporting find($gte, projection)."""

    def __init__(self, docs):
        self._docs = docs

    @staticmethod
    def _naive(dt):
        # pymongo compares/returns UTC-naive datetimes; mimic that so the
        # server-side $gte filter works regardless of the aware/naive bound.
        if dt is not None and dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def find(self, filter=None, projection=None):  # noqa: A002 - mirror pymongo API
        filter = filter or {}
        gte = None
        created = filter.get("created_at")
        if isinstance(created, dict):
            gte = self._naive(created.get("$gte"))
        out = []
        for d in self._docs:
            ts = self._naive(d.get("created_at"))
            if gte is not None and ts is not None and ts < gte:
                continue
            out.append(dict(d))
        return out


def _doc(cost, dt, conv_type):
    return {"cost_usd": cost, "created_at": dt, "conversation_type": conv_type}


def _build_docs_with_baseline():
    """7 preceding days of research spend at 14:00 (mean $2.00) + current-hour spend."""
    docs = []
    # Baseline: each of the 7 preceding days has one research run at 14:05 UTC.
    # Costs 1..3 averaging exactly 2.00 across 7 days.
    per_day_costs = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    for n, c in enumerate(per_day_costs, start=1):
        day = _NOW.date() - timedelta(days=n)
        dt = datetime(day.year, day.month, day.day, 14, 5, tzinfo=timezone.utc)
        docs.append(_doc(c, dt, "research"))

    # Current-hour spend (14:00-14:30 today) for research + execution.
    docs.append(_doc(3.0, _NOW.replace(minute=10), "research"))
    docs.append(_doc(0.5, _NOW.replace(minute=20), "execution"))

    # Some earlier-today spend (not current hour) — counts toward spent_today only.
    docs.append(_doc(4.0, _NOW.replace(hour=9, minute=0), "macro"))
    return docs


class TestCurrentHourCosts:
    def test_returns_all_conv_types(self):
        agg = CostMonitorAggregator(_FakeAgentRuns([]))
        snap = agg.collect(_NOW)
        assert set(snap.current_hour_costs) == set(CONV_TYPES)
        assert all(v == 0.0 for v in snap.current_hour_costs.values())

    def test_sums_current_hour_per_conv_type(self):
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        snap = agg.collect(_NOW)
        assert snap.current_hour_costs["research"] == 3.0
        assert snap.current_hour_costs["execution"] == 0.5
        # macro spend was at 09:00, not the current hour.
        assert snap.current_hour_costs["macro"] == 0.0

    def test_excludes_baseline_days_from_current_hour(self):
        # Baseline research rows are on prior days at 14:05 — must not leak into
        # today's current-hour total (only today's 14:10 run = 3.0 counts).
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        snap = agg.collect(_NOW)
        assert snap.current_hour_costs["research"] == 3.0


class TestLedgerRows:
    def test_seven_rows_per_conv_type(self):
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        snap = agg.collect(_NOW)
        # 7 preceding days × 6 conv types.
        assert len(snap.ledger_rows) == 7 * len(CONV_TYPES)
        research_rows = [r for r in snap.ledger_rows if r["conv_type"] == "research"]
        assert len(research_rows) == 7
        for r in research_rows:
            assert r["hour"] == 14  # target hour
            assert r["date"] < _NOW.date()
            assert r["date"] >= _NOW.date() - timedelta(days=7)

    def test_ledger_feeds_rolling_avg_out_of_cold_start(self):
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        calc = CostCalculator()
        agg.populate_calculator_ledger(calc, _NOW)

        avg = calc.rolling_7d_avg_same_hour("research", _NOW)
        assert avg == 2.0, f"expected $2.00 baseline, got {avg}"

    def test_conv_type_with_no_history_stays_cold_start(self):
        # strategy never appears -> 7 zero rows -> avg 0.0 -> detector cold-start.
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        calc = CostCalculator()
        agg.populate_calculator_ledger(calc, _NOW)
        assert calc.rolling_7d_avg_same_hour("strategy", _NOW) == 0.0


class TestSpentToday:
    def test_falls_back_to_agent_runs_sum_when_no_tracker(self):
        agg = CostMonitorAggregator(_FakeAgentRuns(_build_docs_with_baseline()))
        snap = agg.collect(_NOW)
        # Today's spend = research 3.0 + execution 0.5 + macro 4.0 = 7.5
        assert snap.spent_today_usd == 7.5

    def test_prefers_budget_tracker(self):
        class _Tracker:
            def get_daily_total(self):
                return 42.0

        agg = CostMonitorAggregator(
            _FakeAgentRuns(_build_docs_with_baseline()), budget_tracker=_Tracker()
        )
        snap = agg.collect(_NOW)
        assert snap.spent_today_usd == 42.0

    def test_budget_tracker_failure_falls_back(self):
        class _BadTracker:
            def get_daily_total(self):
                raise RuntimeError("mongo down")

        agg = CostMonitorAggregator(
            _FakeAgentRuns(_build_docs_with_baseline()), budget_tracker=_BadTracker()
        )
        snap = agg.collect(_NOW)
        assert snap.spent_today_usd == 7.5  # fell back to agent_runs sum


class TestTimezoneHandling:
    def test_naive_utc_datetimes_are_handled(self):
        # pymongo returns naive-UTC by default; the aggregator must not choke.
        naive_now = _NOW.replace(tzinfo=None)
        docs = []
        for n in range(1, 8):
            day = naive_now.date() - timedelta(days=n)
            docs.append(_doc(1.0, datetime(day.year, day.month, day.day, 14, 5), "research"))
        docs.append(_doc(2.0, naive_now.replace(minute=10), "research"))

        agg = CostMonitorAggregator(_FakeAgentRuns(docs))
        snap = agg.collect(_NOW)  # aware now, naive docs
        assert snap.current_hour_costs["research"] == 2.0

        calc = CostCalculator()
        agg.populate_calculator_ledger(calc, _NOW)
        assert calc.rolling_7d_avg_same_hour("research", _NOW) == 1.0
