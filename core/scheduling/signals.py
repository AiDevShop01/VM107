"""
Signal accumulation for Brain Layer.

Collects hot signals (task results, failures) for brain cycle consumption.
Thread-safe signal buffering with summary statistics.
"""

import time
import threading
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class Signal:
    """
    Signal emitted by tasks or system events.

    Signals flow from agents/tasks → signal accumulator → brain update loop.
    """
    type: str  # task_result, task_failure, dag_expansion_proposal, goal_proposal, insight, cost_update, regime_change
    source: str  # task_id, goal_id, agent_id
    payload: dict  # Signal-specific data
    timestamp: float  # Unix timestamp when signal emitted
    confidence: float  # Signal confidence (0-1)


class SignalAccumulator:
    """
    Thread-safe signal buffer for brain cycle consumption.

    Collects hot signals in-memory between brain update cycles.
    Provides drain operation to consume signals atomically.
    """

    def __init__(self):
        self._hot_signals: list[Signal] = []
        self._lock = threading.Lock()

    def emit_signal(self, signal: Signal) -> None:
        """
        Add signal to hot buffer.

        Thread-safe: uses lock to protect list append.
        """
        with self._lock:
            self._hot_signals.append(signal)

    def drain_hot_signals(self) -> list[Signal]:
        """
        Return all accumulated signals and clear buffer.

        Thread-safe: atomically swaps buffer and returns old contents.
        """
        with self._lock:
            signals = self._hot_signals
            self._hot_signals = []
            return signals

    def get_signal_summary(self) -> dict:
        """
        Return aggregated signal statistics without draining.

        For monitoring and debugging brain cycle inputs.
        """
        with self._lock:
            signals = self._hot_signals.copy()

        if not signals:
            return {
                "total_count": 0,
                "by_type": {},
                "avg_confidence": 0.0
            }

        # Aggregate by type
        by_type = defaultdict(int)
        total_confidence = 0.0

        for signal in signals:
            by_type[signal.type] += 1
            total_confidence += signal.confidence

        return {
            "total_count": len(signals),
            "by_type": dict(by_type),
            "avg_confidence": total_confidence / len(signals) if signals else 0.0
        }
