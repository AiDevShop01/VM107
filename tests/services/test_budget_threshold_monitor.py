"""BudgetThresholdMonitor tests — RED scaffold (Phase 74 Plan 02).

Tests written FIRST per TDD protocol. All should fail until
VM107/services/budget_threshold_monitor.py is implemented.

Verifies REQ-74-7 + CONTEXT §22:
- 79% spend → no observation
- 80% spend → WARNING observation (threshold-crossing semantics)
- 100% spend → CRITICAL observation
- 120% spend → CRITICAL observation + router.tier_down_for_overage() called
  with NON_TRADE_PATH_CONV_TYPES only (pre-trade/execution/macro NEVER in set)
- Re-crossing same threshold within same day → NO duplicate emission
- Day rollover resets crossing state
- trading_impact=False on all budget observations (CONTEXT §22 lock)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

# Env vars must be set before importing budget_threshold_monitor
os.environ.setdefault("VM107_SUPERVISORY_REDIS_URL", "redis://localhost:6379/3")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_WARN", "3.0")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_CRITICAL", "5.0")
os.environ.setdefault("DAILY_AI_BUDGET_USD", "10.0")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)
_BUDGET = 10.0  # matches DAILY_AI_BUDGET_USD env var


def _make_monitor():
    """Build a BudgetThresholdMonitor with a mocked router."""
    from services.budget_threshold_monitor import BudgetThresholdMonitor
    mock_router = MagicMock()
    monitor = BudgetThresholdMonitor(router=mock_router)
    return monitor, mock_router


# ─────────────────────────────────────────────────────────────────────────────
# Threshold crossing tests
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdCrossings:
    """80% / 100% / 120% threshold crossing behavior."""

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_79_percent_no_observation(self, mock_pub):
        """79% of budget → no observation emitted."""
        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=7.9, now=_NOW)  # 79% of $10

        assert obs is None, "79% budget spend must not emit any observation"
        mock_pub.assert_not_called()

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_80_percent_emits_warning(self, mock_pub):
        """80% of budget → WARNING observation."""
        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=8.0, now=_NOW)  # exactly 80%

        assert obs is not None
        assert obs.severity == "WARNING"
        assert obs.category == "cost_anomaly"
        mock_pub.assert_called_once_with(obs)

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_100_percent_emits_critical(self, mock_pub):
        """100% of budget → CRITICAL observation."""
        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=10.0, now=_NOW)  # 100%

        assert obs is not None
        assert obs.severity == "CRITICAL"
        assert obs.category == "cost_anomaly"

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_120_percent_emits_critical_plus_tier_down(self, mock_pub):
        """120% of budget → CRITICAL observation + router tier-down called."""
        from services.budget_threshold_monitor import NON_TRADE_PATH_CONV_TYPES

        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=12.0, now=_NOW)  # 120%

        assert obs is not None
        assert obs.severity == "CRITICAL"
        # Router tier-down must be called with NON_TRADE_PATH_CONV_TYPES only
        mock_router.tier_down_for_overage.assert_called_once_with(NON_TRADE_PATH_CONV_TYPES)

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_120_percent_tier_down_excludes_trade_path_types(self, mock_pub):
        """At 120%, tier_down_for_overage is NEVER called with trade-path conv types."""
        from services.budget_threshold_monitor import TRADE_PATH_CONV_TYPES, NON_TRADE_PATH_CONV_TYPES

        monitor, mock_router = _make_monitor()
        monitor.evaluate(spent_today_usd=12.0, now=_NOW)

        # Verify the argument passed to tier_down_for_overage
        args, _ = mock_router.tier_down_for_overage.call_args
        conv_types_passed = args[0]

        trade_path_in_arg = conv_types_passed & TRADE_PATH_CONV_TYPES
        assert not trade_path_in_arg, (
            f"Trade-path conv types must NEVER be in tier_down_for_overage argument. "
            f"Found: {trade_path_in_arg} (REQ-74-7 + CONTEXT §22 lock)"
        )

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_trigger_event_id_has_threshold_name(self, mock_pub):
        """trigger_event_id includes 'budget_threshold_crossed' string."""
        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=8.0, now=_NOW)

        assert obs is not None
        assert "budget_threshold_crossed" in obs.trigger_event_id

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_trading_impact_is_false(self, mock_pub):
        """Budget observations must have trading_impact=False (CONTEXT §22 — never hard-cut)."""
        monitor, mock_router = _make_monitor()
        obs = monitor.evaluate(spent_today_usd=8.0, now=_NOW)

        assert obs is not None
        assert obs.trading_impact is False, (
            "Budget monitor must never set trading_impact=True (CONTEXT §22 lock)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Threshold-crossing semantics (no duplicates within same day)
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdCrossingSemantics:
    """Re-crossing same threshold within same day must NOT emit a duplicate."""

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_re_crossing_80_percent_same_day_no_duplicate(self, mock_pub):
        """Once 80% is crossed today, subsequent calls at ≥80% do not re-emit."""
        monitor, mock_router = _make_monitor()

        # First crossing at 80%
        obs1 = monitor.evaluate(spent_today_usd=8.0, now=_NOW)
        assert obs1 is not None
        assert obs1.severity == "WARNING"

        # Re-evaluate at 85% — same threshold already crossed today
        t2 = _NOW.replace(hour=15)
        obs2 = monitor.evaluate(spent_today_usd=8.5, now=t2)
        assert obs2 is None, (
            "Re-crossing 80% threshold within same day must NOT emit duplicate"
        )

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_crossing_higher_threshold_after_lower(self, mock_pub):
        """After 80% warning, crossing 100% emits a new CRITICAL (different threshold)."""
        monitor, mock_router = _make_monitor()

        # Cross 80% first
        obs1 = monitor.evaluate(spent_today_usd=8.0, now=_NOW)
        assert obs1 is not None and obs1.severity == "WARNING"

        # Now cross 100% (new threshold — should emit)
        t2 = _NOW.replace(hour=15)
        obs2 = monitor.evaluate(spent_today_usd=10.0, now=t2)
        assert obs2 is not None
        assert obs2.severity == "CRITICAL"

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_day_rollover_resets_crossing_state(self, mock_pub):
        """Day rollover: 80% warning can re-fire on the next calendar day."""
        monitor, mock_router = _make_monitor()

        # Cross 80% on day 1
        obs1 = monitor.evaluate(spent_today_usd=8.0, now=_NOW)
        assert obs1 is not None

        # Next day, same threshold at 80% → should fire again
        next_day = datetime(2026, 6, 4, 14, 0, 0, tzinfo=timezone.utc)
        obs2 = monitor.evaluate(spent_today_usd=8.0, now=next_day)
        assert obs2 is not None, (
            "Day rollover must reset crossing state — 80% warning should re-fire on next day"
        )
        assert obs2.severity == "WARNING"

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_tier_down_only_fires_once_per_day(self, mock_pub):
        """120% tier-down fires once per day — not on every subsequent call."""
        from services.budget_threshold_monitor import NON_TRADE_PATH_CONV_TYPES

        monitor, mock_router = _make_monitor()

        # First 120% crossing
        monitor.evaluate(spent_today_usd=12.0, now=_NOW)
        assert mock_router.tier_down_for_overage.call_count == 1

        # Second call at 130% — same day, tier_down already fired
        t2 = _NOW.replace(hour=15)
        monitor.evaluate(spent_today_usd=13.0, now=t2)
        assert mock_router.tier_down_for_overage.call_count == 1, (
            "tier_down_for_overage must only fire once per day (threshold-crossing semantics)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Trade-path types must NEVER tier-down
# ─────────────────────────────────────────────────────────────────────────────

class TestTradePathNeverTieredDown:
    """Explicit verification that trade-path types are not included in tier-down set."""

    def test_non_trade_path_conv_types_set(self):
        """NON_TRADE_PATH_CONV_TYPES contains exactly research, strategy, reflection."""
        from services.budget_threshold_monitor import NON_TRADE_PATH_CONV_TYPES, TRADE_PATH_CONV_TYPES

        assert "research" in NON_TRADE_PATH_CONV_TYPES
        assert "strategy" in NON_TRADE_PATH_CONV_TYPES
        assert "reflection" in NON_TRADE_PATH_CONV_TYPES

    def test_trade_path_types_not_in_non_trade_path_set(self):
        """pre-trade, execution, macro must NOT be in NON_TRADE_PATH_CONV_TYPES."""
        from services.budget_threshold_monitor import NON_TRADE_PATH_CONV_TYPES

        assert "pre-trade" not in NON_TRADE_PATH_CONV_TYPES, (
            "pre-trade is a trade-path type — must NEVER tier-down (CONTEXT §22 lock)"
        )
        assert "execution" not in NON_TRADE_PATH_CONV_TYPES, (
            "execution is a trade-path type — must NEVER tier-down (CONTEXT §22 lock)"
        )
        assert "macro" not in NON_TRADE_PATH_CONV_TYPES, (
            "macro is a trade-path type — must NEVER tier-down (CONTEXT §22 lock)"
        )

    def test_disjoint_sets(self):
        """TRADE_PATH and NON_TRADE_PATH sets must be disjoint (no overlap)."""
        from services.budget_threshold_monitor import NON_TRADE_PATH_CONV_TYPES, TRADE_PATH_CONV_TYPES

        overlap = TRADE_PATH_CONV_TYPES & NON_TRADE_PATH_CONV_TYPES
        assert not overlap, (
            f"TRADE_PATH and NON_TRADE_PATH sets must be disjoint. Overlap: {overlap}"
        )
