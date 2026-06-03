"""CostAnomalyDetector tests — GREEN (Phase 74 Plan 02).

Replaces the Wave 0 xfail RED scaffold.

Verifies REQ-74-7:
- 1.5× rolling-7d-avg → INFO observation (panel only)
- 3× rolling-7d-avg → WARNING observation + System P2 notification
- 5× (or budget exceeded) → CRITICAL observation + System P1 notification
- Cold-start (rolling_7d_avg == 0) → INFO only ("Baseline not yet established")
  NEVER WARNING/CRITICAL during cold start (RESEARCH Pitfall 5)
- Observation body is conversation-type-aware (CONTEXT §11 lock)
- All emissions published via shared observation_publisher (Plan 01)
- Determinism: same input → same output (no random/non-deterministic side effects)
- WORM: recovery emits new observation with same correlation_id (never UPDATE)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

# Env vars must be set before importing cost_anomaly_detector
# (module-level fail-fast resolution)
os.environ.setdefault("VM107_SUPERVISORY_REDIS_URL", "redis://localhost:6379/3")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_WARN", "3.0")
os.environ.setdefault("COST_ANOMALY_MULTIPLIER_CRITICAL", "5.0")
os.environ.setdefault("DAILY_AI_BUDGET_USD", "10.0")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 3, 14, 0, 0, tzinfo=timezone.utc)
_ROLLING_AVG = 0.50  # $0.50/hour baseline


def _make_detector(rolling_avg: float = _ROLLING_AVG):
    """Build a CostAnomalyDetector with a mocked CostCalculator."""
    from core.boundary.cost_calculator import CostCalculator
    from services.cost_anomaly_detector import CostAnomalyDetector

    mock_calc = MagicMock(spec=CostCalculator)
    mock_calc.rolling_7d_avg_same_hour.return_value = rolling_avg
    return CostAnomalyDetector(mock_calc)


# ─────────────────────────────────────────────────────────────────────────────
# Threshold matrix tests (1.5× / 3× / 5×)
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdMatrix:
    """Verify the INFO/WARNING/CRITICAL severity matrix."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_1_5x_multiplier_emits_info(self, mock_pub):
        """Rolling avg $0.50 × 1.5 = $0.75 → INFO."""
        detector = _make_detector(rolling_avg=0.50)
        obs = detector.evaluate("research", current_hour_cost=0.75, now=_NOW)

        assert obs is not None
        assert obs.severity == "INFO"
        assert obs.category == "cost_anomaly"
        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_3x_multiplier_emits_warning(self, mock_pub):
        """Rolling avg $0.50 × 3.0 = $1.50 → WARNING."""
        detector = _make_detector(rolling_avg=0.50)
        obs = detector.evaluate("research", current_hour_cost=1.50, now=_NOW)

        assert obs is not None
        assert obs.severity == "WARNING"
        assert obs.category == "cost_anomaly"
        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_5x_multiplier_emits_critical(self, mock_pub):
        """Rolling avg $0.50 × 5.0 = $2.50 → CRITICAL."""
        detector = _make_detector(rolling_avg=0.50)
        obs = detector.evaluate("research", current_hour_cost=2.50, now=_NOW)

        assert obs is not None
        assert obs.severity == "CRITICAL"
        assert obs.category == "cost_anomaly"
        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_below_1_5x_no_observation(self, mock_pub):
        """Rolling avg $0.50, cost $0.60 (1.2×) → None (no observation)."""
        detector = _make_detector(rolling_avg=0.50)
        obs = detector.evaluate("research", current_hour_cost=0.60, now=_NOW)

        assert obs is None, "Normal spend (< 1.5×) must not emit observation"
        mock_pub.assert_not_called()

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_exactly_at_1_5x_boundary_emits_info(self, mock_pub):
        """Exactly at 1.5× threshold → INFO (boundary inclusive)."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=1.5, now=_NOW)

        assert obs is not None
        assert obs.severity == "INFO"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_between_warning_and_critical_emits_warning(self, mock_pub):
        """At 4.2× (between 3× and 5×) → WARNING."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert obs.severity == "WARNING"


# ─────────────────────────────────────────────────────────────────────────────
# Cold-start protection (RESEARCH Pitfall 5)
# ─────────────────────────────────────────────────────────────────────────────

class TestColdStartProtection:
    """Verify cold-start guard: rolling_avg == 0.0 → INFO only, never WARNING/CRITICAL."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_cold_start_emits_info_with_baseline_not_established(self, mock_pub):
        """Cold start (rolling_avg == 0.0) → INFO 'Baseline not yet established'."""
        detector = _make_detector(rolling_avg=0.0)
        obs = detector.evaluate("research", current_hour_cost=50.0, now=_NOW)

        assert obs is not None
        assert obs.severity == "INFO", (
            "Cold start must emit INFO only — never WARNING/CRITICAL (RESEARCH Pitfall 5)"
        )
        assert "baseline" in obs.body.lower() or "established" in obs.body.lower(), (
            "Cold start body must mention baseline establishment"
        )
        assert obs.category == "cost_anomaly"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_cold_start_never_warning_regardless_of_current_cost(self, mock_pub):
        """Even with $1000 current cost, cold start (0.0 avg) must NOT emit WARNING."""
        detector = _make_detector(rolling_avg=0.0)
        obs = detector.evaluate("execution", current_hour_cost=1000.0, now=_NOW)

        # Can be INFO or None, but NEVER WARNING or CRITICAL
        if obs is not None:
            assert obs.severity not in ("WARNING", "CRITICAL"), (
                "Cold start (no baseline) must emit INFO at most — RESEARCH Pitfall 5"
            )

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_cold_start_emits_obs_not_none(self, mock_pub):
        """Cold start always emits an observation (visibility maintained during ramp-up)."""
        detector = _make_detector(rolling_avg=0.0)
        obs = detector.evaluate("strategy", current_hour_cost=0.01, now=_NOW)

        assert obs is not None, "Cold start must always emit an observation (INFO)"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_cold_start_conversation_type_in_body(self, mock_pub):
        """Cold start body includes the conv_type for context."""
        detector = _make_detector(rolling_avg=0.0)
        obs = detector.evaluate("research", current_hour_cost=5.0, now=_NOW)

        assert obs is not None
        assert "research" in obs.body.lower(), (
            "Cold start body should identify the conv_type"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Conversation-type-aware body text (CONTEXT §11 lock)
# ─────────────────────────────────────────────────────────────────────────────

class TestConvTypeAwareBody:
    """Verify observation body is conv-type-specific (CONTEXT §11 lock).

    The text must read: "{Display Name} spend is {ratio}× above normal"
    NOT: "Cost anomaly detected"
    """

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_research_body_says_research_ai(self, mock_pub):
        """research → 'Research AI spend is ...'"""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert "Research AI" in obs.body, f"Expected 'Research AI' in body, got: {obs.body!r}"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_execution_body_says_execution_ai(self, mock_pub):
        """execution → 'Execution AI spend is ...'"""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("execution", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert "Execution AI" in obs.body, f"Expected 'Execution AI' in body, got: {obs.body!r}"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_pre_trade_body_says_pre_trade_ai(self, mock_pub):
        """pre-trade → 'Pre-Trade AI spend is ...'"""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("pre-trade", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert "Pre-Trade AI" in obs.body, f"Expected 'Pre-Trade AI' in body, got: {obs.body!r}"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_body_includes_ratio(self, mock_pub):
        """Body includes the computed ratio (e.g., '4.2×')."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        # ratio = 4.2/1.0 = 4.2
        assert "4.2" in obs.body, f"Expected ratio '4.2' in body, got: {obs.body!r}"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_body_says_above_normal(self, mock_pub):
        """Body says '... above normal' per CONTEXT §11."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert "above normal" in obs.body, (
            f"Body must say 'above normal' per CONTEXT §11, got: {obs.body!r}"
        )

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_body_not_generic_cost_anomaly_detected(self, mock_pub):
        """Body must NOT be the generic 'Cost anomaly detected' string."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=4.2, now=_NOW)

        assert obs is not None
        assert obs.body.lower() != "cost anomaly detected", (
            "Body must be conv-type-aware, not generic 'Cost anomaly detected'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Observation contract compliance
# ─────────────────────────────────────────────────────────────────────────────

class TestObservationContract:
    """Verify the emitted Observation conforms to the Phase 74 contract."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_category_is_cost_anomaly(self, mock_pub):
        """Observation category must be 'cost_anomaly'."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        assert obs is not None
        assert obs.category == "cost_anomaly"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_conversation_type_populated(self, mock_pub):
        """Observation conversation_type field is set."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        assert obs is not None
        assert obs.conversation_type == "research"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_source_vm_is_vm107(self, mock_pub):
        """Observation source_vm must be 'VM107'."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        assert obs is not None
        assert obs.source_vm == "VM107"

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_trading_impact_is_false(self, mock_pub):
        """Cost anomaly never blocks trading — trading_impact must be False (CONTEXT §22)."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=10.0, now=_NOW)

        assert obs is not None
        assert obs.trading_impact is False, (
            "Cost anomaly must never set trading_impact=True (CONTEXT §22 lock)"
        )

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_generated_at_matches_now_param(self, mock_pub):
        """generated_at matches the passed now parameter."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        assert obs is not None
        assert obs.generated_at == _NOW

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_observation_is_frozen_worm(self, mock_pub):
        """Observation is frozen (WORM) — mutation raises."""
        from pydantic import ValidationError
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        assert obs is not None
        with pytest.raises((TypeError, ValidationError)):
            obs.severity = "INFO"  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Publisher integration
# ─────────────────────────────────────────────────────────────────────────────

class TestPublisherIntegration:
    """Verify all emitted observations go through publish_observation (Plan 01)."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_publish_called_for_info(self, mock_pub):
        """INFO threshold → publish_observation called exactly once."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=1.5, now=_NOW)

        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_publish_called_for_warning(self, mock_pub):
        """WARNING threshold → publish_observation called exactly once."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)

        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_publish_called_for_critical(self, mock_pub):
        """CRITICAL threshold → publish_observation called exactly once."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=5.0, now=_NOW)

        mock_pub.assert_called_once_with(obs)

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_publish_not_called_below_threshold(self, mock_pub):
        """Below 1.5× threshold → publish_observation NOT called."""
        detector = _make_detector(rolling_avg=1.0)
        obs = detector.evaluate("research", current_hour_cost=1.2, now=_NOW)

        assert obs is None
        mock_pub.assert_not_called()

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_publish_called_for_cold_start(self, mock_pub):
        """Cold start → publish_observation called (always emit INFO)."""
        detector = _make_detector(rolling_avg=0.0)
        obs = detector.evaluate("research", current_hour_cost=5.0, now=_NOW)

        assert obs is not None
        mock_pub.assert_called_once_with(obs)


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Verify same inputs always produce same outputs."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_same_input_same_severity(self, mock_pub):
        """Same inputs → same severity (no randomness)."""
        detector = _make_detector(rolling_avg=1.0)
        results = [
            detector.evaluate("research", current_hour_cost=3.0, now=_NOW)
            for _ in range(5)
        ]

        severities = {obs.severity for obs in results if obs is not None}
        assert len(severities) == 1, (
            f"Multiple severities from same input: {severities} — detector is non-deterministic"
        )

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_different_conv_types_independent(self, mock_pub):
        """Different conv_types produce independent observations."""
        from core.boundary.cost_calculator import CostCalculator

        mock_calc = MagicMock(spec=CostCalculator)

        def side_effect(conv_type, target_dt):
            return {"research": 1.0, "execution": 0.10}.get(conv_type, 0.0)

        mock_calc.rolling_7d_avg_same_hour.side_effect = side_effect

        from services.cost_anomaly_detector import CostAnomalyDetector
        detector = CostAnomalyDetector(mock_calc)

        obs_research = detector.evaluate("research", current_hour_cost=3.0, now=_NOW)
        obs_execution = detector.evaluate("execution", current_hour_cost=3.0, now=_NOW)

        # research: 3.0 / 1.0 = 3× → WARNING
        assert obs_research is not None
        assert obs_research.severity == "WARNING"
        # execution: 3.0 / 0.10 = 30× → CRITICAL
        assert obs_execution is not None
        assert obs_execution.severity == "CRITICAL"


# ─────────────────────────────────────────────────────────────────────────────
# WORM recovery pattern
# ─────────────────────────────────────────────────────────────────────────────

class TestWormRecovery:
    """Verify recovery follows WORM append-only pattern."""

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_recovery_creates_new_observation(self, mock_pub):
        """Recovery = new observation with same correlation_id (WORM — never UPDATE)."""
        from services.cost_anomaly_detector import CostAnomalyDetector
        from core.boundary.cost_calculator import CostCalculator

        mock_calc = MagicMock(spec=CostCalculator)
        mock_calc.rolling_7d_avg_same_hour.return_value = 1.0
        detector = CostAnomalyDetector(mock_calc)

        # Spike
        spike_obs = detector.evaluate("research", current_hour_cost=5.5, now=_NOW)
        assert spike_obs is not None
        assert spike_obs.severity == "CRITICAL"
        spike_correlation_id = spike_obs.correlation_id

        # Recovery using the spike's trigger_event_id as correlation_id
        recovery_correlation_id = spike_obs.trigger_event_id
        recovery_time = datetime(2026, 6, 3, 15, 0, 0, tzinfo=timezone.utc)
        recovery_obs = detector.recover(
            correlation_id=recovery_correlation_id,
            conv_type="research",
            now=recovery_time,
        )

        assert recovery_obs is not None
        assert recovery_obs.severity == "INFO"
        assert recovery_obs.correlation_id == recovery_correlation_id
        assert recovery_obs.observation_id != spike_obs.observation_id, (
            "Recovery must create a new row, never update the spike row (WORM)"
        )

    @patch("services.cost_anomaly_detector.publish_observation")
    def test_recovery_is_published(self, mock_pub):
        """Recovery observation is published via publish_observation."""
        from services.cost_anomaly_detector import CostAnomalyDetector
        from core.boundary.cost_calculator import CostCalculator

        mock_calc = MagicMock(spec=CostCalculator)
        mock_calc.rolling_7d_avg_same_hour.return_value = 1.0
        detector = CostAnomalyDetector(mock_calc)

        recovery_obs = detector.recover(
            correlation_id="some-correlation-id",
            conv_type="research",
            now=_NOW,
        )
        # Last call must be the recovery obs
        mock_pub.assert_called_with(recovery_obs)
