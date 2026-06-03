"""ModelRouter.tier_down_for_overage tests — RED scaffold (Phase 74 Plan 02).

Tests written FIRST per TDD protocol. All should fail until
tier_down_for_overage() is added to VM107/core/routing/router.py.

Verifies REQ-74-7 + CONTEXT §22 trade-path protection lock:
- tier_down_for_overage(non_trade_path_types) succeeds for valid sets
- tier_down_for_overage raises ValueError if any trade-path type included
  (pre-trade, execution, macro are PROTECTED — CONTEXT §22 lock)
- Router _conv_type_overrides updated for non-trade-path types after tier-down
- Passing empty set is a no-op (no override changes)
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure VM107 root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("VM107_SUPERVISORY_REDIS_URL", "redis://localhost:6379/3")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_WARN", "3.0")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_CRITICAL", "5.0")
os.environ.setdefault("DAILY_AI_BUDGET_USD", "10.0")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_router():
    """Build a minimal ModelRouter for tier_down testing."""
    from core.routing.router import ModelRouter

    router = ModelRouter.__new__(ModelRouter)
    router._conv_type_overrides = {}
    router._fallback_model_for = MagicMock(return_value="ollama/llama3.2")
    router.log = MagicMock()
    return router


# ─────────────────────────────────────────────────────────────────────────────
# tier_down_for_overage method existence
# ─────────────────────────────────────────────────────────────────────────────

class TestTierDownMethodExists:
    """Verify the method is present and callable."""

    def test_tier_down_for_overage_exists(self):
        """ModelRouter must have a tier_down_for_overage method (Plan 02 contract)."""
        from core.routing.router import ModelRouter
        assert hasattr(ModelRouter, "tier_down_for_overage"), (
            "ModelRouter.tier_down_for_overage() must be added by Plan 02"
        )
        assert callable(getattr(ModelRouter, "tier_down_for_overage"))


# ─────────────────────────────────────────────────────────────────────────────
# Trade-path protection (CONTEXT §22 lock — ValueError guard)
# ─────────────────────────────────────────────────────────────────────────────

class TestTradePathProtection:
    """Trade-path conv types are PROTECTED from tier-down — raises ValueError."""

    def test_raises_if_pre_trade_included(self):
        """Passing 'pre-trade' raises ValueError (trade-path lock)."""
        router = _make_router()
        with pytest.raises(ValueError, match="pre-trade"):
            router.tier_down_for_overage(frozenset({"pre-trade", "research"}))

    def test_raises_if_execution_included(self):
        """Passing 'execution' raises ValueError (trade-path lock)."""
        router = _make_router()
        with pytest.raises(ValueError, match="execution"):
            router.tier_down_for_overage(frozenset({"execution"}))

    def test_raises_if_macro_included(self):
        """Passing 'macro' raises ValueError (trade-path lock)."""
        router = _make_router()
        with pytest.raises(ValueError, match="macro"):
            router.tier_down_for_overage(frozenset({"macro", "strategy"}))

    def test_raises_if_all_trade_path_included(self):
        """Passing all 3 trade-path types raises ValueError."""
        router = _make_router()
        with pytest.raises(ValueError):
            router.tier_down_for_overage(frozenset({"pre-trade", "execution", "macro"}))

    def test_error_message_mentions_context_lock(self):
        """ValueError message must be informative about the protection lock."""
        router = _make_router()
        with pytest.raises(ValueError) as exc_info:
            router.tier_down_for_overage(frozenset({"execution"}))

        # Error message should mention the protection context
        error_msg = str(exc_info.value)
        assert any(term in error_msg.lower() for term in ["protect", "trade-path", "execution", "context"]), (
            f"ValueError must explain the CONTEXT §22 lock. Got: {error_msg!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Non-trade-path tier-down (should succeed)
# ─────────────────────────────────────────────────────────────────────────────

class TestNonTradePathTierDown:
    """Non-trade-path conv types should tier-down successfully."""

    def test_non_trade_path_tier_down_succeeds(self):
        """Tier-down with only non-trade-path types succeeds without error."""
        router = _make_router()
        # Should not raise
        router.tier_down_for_overage(frozenset({"research", "strategy", "reflection"}))

    def test_tier_down_updates_conv_type_overrides(self):
        """After tier-down, _conv_type_overrides contains entries for affected types."""
        router = _make_router()
        router.tier_down_for_overage(frozenset({"research", "strategy"}))

        assert "research" in router._conv_type_overrides, (
            "research conv_type should have an override after tier_down_for_overage"
        )
        assert "strategy" in router._conv_type_overrides, (
            "strategy conv_type should have an override after tier_down_for_overage"
        )

    def test_tier_down_sets_fallback_model(self):
        """_conv_type_overrides values come from _fallback_model_for()."""
        router = _make_router()
        router._fallback_model_for.return_value = "ollama/llama3.2"
        router.tier_down_for_overage(frozenset({"research"}))

        assert router._conv_type_overrides.get("research") == "ollama/llama3.2"

    def test_empty_set_is_noop(self):
        """Passing empty set is a no-op — no overrides changed, no error."""
        router = _make_router()
        router.tier_down_for_overage(frozenset())

        assert router._conv_type_overrides == {}, (
            "Empty conv_types set must not modify _conv_type_overrides"
        )

    def test_single_research_type_succeeds(self):
        """Single non-trade-path type (research) succeeds."""
        router = _make_router()
        router.tier_down_for_overage(frozenset({"research"}))
        assert "research" in router._conv_type_overrides


# ─────────────────────────────────────────────────────────────────────────────
# Boundary test: 120% budget path from BudgetThresholdMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetMonitorRouterIntegration:
    """Integration: BudgetThresholdMonitor calls router correctly at 120%."""

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_at_120_percent_router_called_with_non_trade_path_only(self, mock_pub):
        """At 120% budget, router.tier_down_for_overage gets NON_TRADE_PATH_CONV_TYPES."""
        from services.budget_threshold_monitor import (
            BudgetThresholdMonitor,
            TRADE_PATH_CONV_TYPES,
            NON_TRADE_PATH_CONV_TYPES,
        )
        from datetime import datetime, timezone

        router = _make_router()
        monitor = BudgetThresholdMonitor(router=router)
        now = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)

        monitor.evaluate(spent_today_usd=12.0, now=now)  # 120% of $10

        router._fallback_model_for.assert_called()
        # All called types should be non-trade-path
        for ct in router._conv_type_overrides:
            assert ct not in TRADE_PATH_CONV_TYPES, (
                f"Trade-path type '{ct}' found in tier-down overrides — "
                "violates CONTEXT §22 lock (REQ-74-7)"
            )

    @patch("services.budget_threshold_monitor.publish_observation")
    def test_at_120_percent_trade_path_never_in_tier_down(self, mock_pub):
        """Explicit assertion: pre-trade, execution, macro NEVER in tier-down overrides."""
        from services.budget_threshold_monitor import BudgetThresholdMonitor
        from datetime import datetime, timezone

        router = _make_router()
        monitor = BudgetThresholdMonitor(router=router)
        now = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)

        monitor.evaluate(spent_today_usd=12.0, now=now)

        for protected_type in ("pre-trade", "execution", "macro"):
            assert protected_type not in router._conv_type_overrides, (
                f"'{protected_type}' must NEVER appear in tier-down overrides "
                f"(REQ-74-7 trade-path protection lock)"
            )
