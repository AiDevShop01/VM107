"""Cost anomaly detector tests — RED scaffold, Wave 1 implements.

Verifies REQ-74-7:
- 1.5× rolling-7d-avg → INFO observation (panel only)
- 3× rolling-7d-avg → WARNING observation + System P2 notification
- 5× (or budget exceeded) → CRITICAL observation + System P1 notification
- Cold-start (rolling_7d_avg == 0) → INFO only (no false positives)
- WORM: recovery emits new observation with same correlation_id (never UPDATE)
"""
import pytest

pytestmark = pytest.mark.xfail(
    strict=True, reason="Wave 1 (Plan 01) implements VM107/services/cost_anomaly_detector.py"
)


def test_1_5x_multiplier_emits_info():
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    obs = detector.evaluate(current_hour_cost=15.0)  # 1.5x
    assert obs is not None
    assert obs.severity == "INFO"
    assert obs.category == "cost_anomaly"


def test_3x_multiplier_emits_warning():
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    obs = detector.evaluate(current_hour_cost=30.0)  # 3.0x
    assert obs is not None
    assert obs.severity == "WARNING"


def test_5x_multiplier_emits_critical():
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    obs = detector.evaluate(current_hour_cost=50.0)  # 5.0x
    assert obs is not None
    assert obs.severity == "CRITICAL"


def test_below_1_5x_no_observation():
    """No observation emitted for normal spend (below 1.5x threshold)."""
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    obs = detector.evaluate(current_hour_cost=12.0)  # 1.2x — normal
    assert obs is None, "Normal spend (< 1.5x) must not emit observation"


def test_cold_start_emits_info_only():
    """Cold start (rolling_7d_avg == 0) must emit INFO at most — no false positives."""
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=0.0)
    obs = detector.evaluate(current_hour_cost=50.0)
    if obs is not None:
        assert obs.severity == "INFO", (
            "Cold start (no baseline) must emit INFO at most — RESEARCH Pitfall 5"
        )


def test_observation_is_conversation_type_aware():
    """Cost anomaly body should identify which conv-type caused the spike."""
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    obs = detector.evaluate(
        current_hour_cost=35.0,  # 3.5x
        conversation_type="research",
    )
    assert obs is not None
    assert "research" in obs.body.lower() or obs.conversation_type == "research", (
        "Cost anomaly observation should be conversation-type-aware — CONTEXT §11"
    )


def test_recovery_creates_new_observation():
    """Recovery from anomaly = new observation with same correlation_id (WORM)."""
    from services.cost_anomaly_detector import CostAnomalyDetector

    detector = CostAnomalyDetector(rolling_7d_avg_same_hour=10.0)
    # Spike
    spike_obs = detector.evaluate(current_hour_cost=55.0)
    assert spike_obs.severity == "CRITICAL"
    correlation_id = spike_obs.correlation_id

    # Recovery
    recovery_obs = detector.recover(correlation_id=correlation_id)
    assert recovery_obs is not None
    assert recovery_obs.severity == "INFO"
    assert recovery_obs.correlation_id == correlation_id
    assert recovery_obs.observation_id != spike_obs.observation_id, (
        "Recovery must create a new row, never update the spike row (WORM)"
    )
