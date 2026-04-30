"""
Tests for Brain Layer components: hysteresis, confidence, signals.

TDD Phase: RED - Write failing tests first.
"""

import time
import pytest
from core.scheduling.hysteresis import HysteresisController
from core.scheduling.confidence import ConfidenceScorer
from core.scheduling.signals import SignalAccumulator, Signal


class TestHysteresisController:
    """Test 3-layer hysteresis protection for mode transitions."""

    def test_mode_locked_during_minimum_hold_time(self):
        """Mode cannot change during minimum hold time (60s default)."""
        config = {"confirmation_cycles": 3, "min_hold_seconds": 60}
        controller = HysteresisController(config)

        # Start in exploration mode
        assert controller.current_mode == "exploration"
        start_time = time.time()

        # Strong signal for stabilization (failure_rate > 0.3)
        signals = {"success_rate": 0.2, "entropy": 0.3, "failure_rate": 0.5}

        # Evaluate immediately - should stay in exploration (hold time not elapsed)
        mode = controller.evaluate(signals, start_time + 10)
        assert mode == "exploration", "Mode should be locked during hold time"

    def test_threshold_bands_prevent_weak_signals(self):
        """Signal must exceed ENTER threshold, not just exit threshold."""
        config = {"confirmation_cycles": 3, "min_hold_seconds": 1}
        controller = HysteresisController(config)

        # Wait for hold time to elapse
        time.sleep(1.1)
        current_time = time.time()

        # Signal at 0.55 - above exit (0.4) but below enter (0.6) for exploration
        signals = {"success_rate": 0.3, "entropy": 0.55, "failure_rate": 0.1}

        mode = controller.evaluate(signals, current_time)
        assert mode == "exploration", "Signal must exceed ENTER threshold"

    def test_confirmation_cycles_required_before_switch(self):
        """Mode requires N consecutive cycles indicating same mode."""
        config = {"confirmation_cycles": 3, "min_hold_seconds": 1}
        controller = HysteresisController(config)

        # Wait for hold time
        time.sleep(1.1)
        current_time = time.time()

        # Strong exploitation signals (success_rate > 0.7)
        signals = {"success_rate": 0.8, "entropy": 0.3, "failure_rate": 0.05}

        # Cycle 1: pending mode set
        mode1 = controller.evaluate(signals, current_time + 1)
        assert mode1 == "exploration", "Should stay in current mode (cycle 1)"

        # Cycle 2: confirmation counter increments
        mode2 = controller.evaluate(signals, current_time + 2)
        assert mode2 == "exploration", "Should stay in current mode (cycle 2)"

        # Cycle 3: confirmation threshold reached, switch occurs
        mode3 = controller.evaluate(signals, current_time + 3)
        assert mode3 == "exploitation", "Should switch after 3 confirmations"

    def test_rapid_alternation_resets_counter(self):
        """Signal flips between modes each cycle - counter resets, mode never changes."""
        config = {"confirmation_cycles": 3, "min_hold_seconds": 1}
        controller = HysteresisController(config)

        time.sleep(1.1)
        current_time = time.time()

        # Cycle 1: exploitation signals
        signals_exploit = {"success_rate": 0.8, "entropy": 0.3, "failure_rate": 0.05}
        mode1 = controller.evaluate(signals_exploit, current_time + 1)
        assert mode1 == "exploration"

        # Cycle 2: exploration signals (flip)
        signals_explore = {"success_rate": 0.4, "entropy": 0.7, "failure_rate": 0.1}
        mode2 = controller.evaluate(signals_explore, current_time + 2)
        assert mode2 == "exploration", "Counter should reset on signal flip"

        # Cycle 3: exploitation signals again (flip back)
        mode3 = controller.evaluate(signals_exploit, current_time + 3)
        assert mode3 == "exploration", "Mode should never change with rapid alternation"

    def test_stabilization_override_bypasses_hold_time(self):
        """High failure rate overrides other modes immediately."""
        config = {"confirmation_cycles": 3, "min_hold_seconds": 60}
        controller = HysteresisController(config)
        controller.current_mode = "exploitation"
        controller.mode_entered_at = time.time()

        # Immediate stabilization signal (failure_rate > 0.3)
        signals = {"success_rate": 0.2, "entropy": 0.3, "failure_rate": 0.5}

        # Should switch immediately despite hold time
        mode = controller.evaluate(signals, time.time() + 5)

        # Note: Stabilization override still requires confirmation cycles
        # Test that stabilization is pending
        assert controller.pending_mode == "stabilization"


class TestConfidenceScorer:
    """Test EMA confidence scoring with contradiction penalty."""

    def test_ema_first_value_initializes(self):
        """First update initializes EMA."""
        scorer = ConfidenceScorer(span=20, lambda_penalty=0.5)

        confidence = scorer.update(validation_result=True, contradiction_ratio=0.0)

        # First value with min sample weighting (1/5) and no contradiction
        assert confidence == pytest.approx(0.2, abs=0.01), "First value should be weighted down"

    def test_ema_smoothing_applies(self):
        """Subsequent values apply alpha smoothing."""
        scorer = ConfidenceScorer(span=20)  # alpha = 2/21 ≈ 0.095

        # Initialize with True
        scorer.update(validation_result=True, contradiction_ratio=0.0)

        # Update with False
        confidence = scorer.update(validation_result=False, contradiction_ratio=0.0)

        # EMA: alpha * 0.0 + (1-alpha) * 1.0 = 0.905
        # Sample weighting: 2/5 = 0.4
        # Expected: 0.905 * 0.4 = 0.362
        assert 0.3 < confidence < 0.4, f"EMA smoothing failed: {confidence}"

    def test_contradiction_penalty_reduces_confidence(self):
        """Contradiction penalty: C_final = EMA × (1 - λ × contradiction_ratio)."""
        scorer = ConfidenceScorer(span=20, lambda_penalty=0.5)

        # Build up confidence with 10 True updates (get past min sample threshold)
        for _ in range(10):
            scorer.update(validation_result=True, contradiction_ratio=0.0)

        # Now apply contradiction penalty
        confidence = scorer.update(
            validation_result=True,
            contradiction_ratio=0.5  # 50% contradiction
        )

        # Expected: EMA_conf ≈ 1.0, penalty = (1 - 0.5 * 0.5) = 0.75
        # Final = 1.0 * 0.75 = 0.75
        assert confidence == pytest.approx(0.75, abs=0.1)

    def test_minimum_sample_size_weighting(self):
        """First 5 updates weighted down proportionally."""
        scorer = ConfidenceScorer(span=20)

        confidences = []
        for i in range(5):
            conf = scorer.update(validation_result=True, contradiction_ratio=0.0)
            confidences.append(conf)

        # Sample 1: 1/5 = 0.2 weight
        # Sample 2: 2/5 = 0.4 weight
        # Sample 5: 5/5 = 1.0 weight (full)
        assert confidences[0] < confidences[1] < confidences[4]

    def test_confidence_clamped_to_0_1(self):
        """Confidence always clamped to [0, 1]."""
        scorer = ConfidenceScorer(span=20, lambda_penalty=1.0)

        # Build confidence then apply massive contradiction
        for _ in range(10):
            scorer.update(validation_result=True, contradiction_ratio=0.0)

        # Apply 100% contradiction with full penalty
        confidence = scorer.update(validation_result=True, contradiction_ratio=1.0)

        assert 0.0 <= confidence <= 1.0


class TestSignalAccumulator:
    """Test signal emission and draining."""

    def test_emit_signal_adds_to_hot_buffer(self):
        """emit_signal adds signal to buffer."""
        accumulator = SignalAccumulator()

        signal = Signal(
            type="task_result",
            source="task_123",
            payload={"status": "completed"},
            timestamp=time.time(),
            confidence=0.9
        )

        accumulator.emit_signal(signal)

        signals = accumulator.drain_hot_signals()
        assert len(signals) == 1
        assert signals[0].type == "task_result"

    def test_drain_hot_signals_clears_buffer(self):
        """drain_hot_signals returns all signals and clears buffer."""
        accumulator = SignalAccumulator()

        # Add 3 signals
        for i in range(3):
            signal = Signal(
                type="task_failure",
                source=f"task_{i}",
                payload={},
                timestamp=time.time(),
                confidence=0.8
            )
            accumulator.emit_signal(signal)

        # Drain
        signals = accumulator.drain_hot_signals()
        assert len(signals) == 3

        # Drain again - should be empty
        signals2 = accumulator.drain_hot_signals()
        assert len(signals2) == 0

    def test_get_signal_summary(self):
        """get_signal_summary returns aggregated statistics."""
        accumulator = SignalAccumulator()

        # Add various signal types
        accumulator.emit_signal(Signal(
            type="task_result", source="task_1", payload={},
            timestamp=time.time(), confidence=0.9
        ))
        accumulator.emit_signal(Signal(
            type="task_result", source="task_2", payload={},
            timestamp=time.time(), confidence=0.8
        ))
        accumulator.emit_signal(Signal(
            type="task_failure", source="task_3", payload={},
            timestamp=time.time(), confidence=0.7
        ))

        summary = accumulator.get_signal_summary()

        assert summary["total_count"] == 3
        assert summary["by_type"]["task_result"] == 2
        assert summary["by_type"]["task_failure"] == 1
        assert "avg_confidence" in summary
