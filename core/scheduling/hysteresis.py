"""
Hysteresis controller for mode transitions.

3-layer protection against mode thrashing:
1. Threshold bands (deadband) - different enter/exit thresholds
2. Confirmation window - N consecutive cycles before switching
3. Minimum hold time - locked after entering mode

Stabilization mode overrides other modes (highest priority).
"""

import time


class HysteresisController:
    """
    3-layer hysteresis for mode transitions: bands + confirmation + hold time.

    Prevents mode flip-flopping under noisy signals by requiring:
    - Signal strength above ENTER threshold (not just EXIT)
    - N consecutive cycles indicating same mode
    - Minimum time in current mode before switching
    """

    def __init__(self, config: dict):
        """
        Args:
            config: {
                "confirmation_cycles": int (default 3),
                "min_hold_seconds": int (default 60)
            }
        """
        # Threshold bands (deadband) — different enter/exit thresholds
        self.thresholds = {
            "exploration": {"enter": 0.6, "exit": 0.4},  # High entropy, low success rate
            "exploitation": {"enter": 0.7, "exit": 0.5},  # High success rate, low entropy
            "stabilization": {"enter": 0.3, "exit": 0.5}  # High failure rate (override)
        }

        # Confirmation cycles — N consecutive cycles before switching
        self.confirmation_cycles = config.get("confirmation_cycles", 3)

        # Minimum hold time — locked after entering mode
        self.min_hold_seconds = config.get("min_hold_seconds", 60)

        # State tracking
        self.current_mode: str = "exploration"  # Default cold start mode
        self.mode_entered_at: float = time.time()
        self.pending_mode: str | None = None
        self.confirmation_counter: int = 0

    def evaluate(self, signals: dict, current_time: float) -> str:
        """
        Evaluate signals and return mode (with hysteresis protection).

        Args:
            signals: {
                "success_rate": float (0-1),
                "entropy": float (0-1),
                "failure_rate": float (0-1)
            }
            current_time: Current timestamp for hold time check

        Returns:
            Current mode string: "exploration", "exploitation", or "stabilization"
        """
        # Compute indicated mode from signals (without hysteresis)
        indicated_mode = self._compute_indicated_mode(signals)

        # Layer 1: Minimum hold time check
        if (current_time - self.mode_entered_at) < self.min_hold_seconds:
            # Mode locked - cannot transition yet
            # But still track pending mode for monitoring
            if indicated_mode != self.current_mode:
                self.pending_mode = indicated_mode
                self.confirmation_counter = 1
            return self.current_mode

        # Layer 2: Threshold bands (deadband)
        # Only consider transition if indicated_mode crosses ENTER threshold
        if indicated_mode != self.current_mode:
            threshold = self.thresholds[indicated_mode]["enter"]
            signal_value = self._get_signal_for_mode(indicated_mode, signals)

            if signal_value < threshold:
                # Signal not strong enough to enter new mode
                return self.current_mode

        # Layer 3: Confirmation cycles
        if indicated_mode == self.pending_mode:
            self.confirmation_counter += 1

            if self.confirmation_counter >= self.confirmation_cycles:
                # Confirmed — switch mode
                self.current_mode = indicated_mode
                self.mode_entered_at = current_time
                self.pending_mode = None
                self.confirmation_counter = 0
        else:
            # Different mode indicated — reset confirmation
            self.pending_mode = indicated_mode
            self.confirmation_counter = 1

        return self.current_mode

    def _compute_indicated_mode(self, signals: dict) -> str:
        """
        Compute mode from signals (no hysteresis).

        Priority:
        1. Stabilization (high failure rate) - overrides other modes
        2. Exploration (high entropy, low success)
        3. Exploitation (high success, low entropy)
        """
        # Stabilization overrides (highest priority)
        if signals["failure_rate"] > 0.3:
            return "stabilization"

        # Exploration vs Exploitation
        if signals["entropy"] > 0.6 and signals["success_rate"] < 0.5:
            return "exploration"
        elif signals["success_rate"] > 0.7:
            return "exploitation"

        return "exploration"  # Default

    def _get_signal_for_mode(self, mode: str, signals: dict) -> float:
        """
        Map mode to primary signal value for threshold check.

        Returns the signal value used to determine if mode ENTER threshold is met.
        """
        if mode == "stabilization":
            return signals["failure_rate"]
        elif mode == "exploration":
            return signals["entropy"]
        else:  # exploitation
            return signals["success_rate"]
