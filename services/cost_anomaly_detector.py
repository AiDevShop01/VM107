"""Deterministic cost anomaly detector (Phase 74 REQ-74-7).

Compares current_hour_cost to rolling_7d_avg_same_hour per conversation type.
Emits Observation at INFO (1.5×) / WARNING (env-configured ×) / CRITICAL (env-configured ×).
Cold-start protection: rolling_7d_avg == 0.0 → INFO only with "Baseline not yet established"
body (RESEARCH Pitfall 5 — never WARNING/CRITICAL without 7d history).

All emissions published via shared observation_publisher (Plan 01) on the
``vm107.observations`` Redis channel.

Anti-patterns (NEVER):
    - LLM calls in the emit/trigger path (deterministic-first lock, CONTEXT §6)
    - Returning WARNING/CRITICAL during cold start (Pitfall 5 lock)
    - Non-deterministic time or random side effects in evaluation
    - Generic body text that omits conversation type (CONTEXT §11)
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fingpt_core.contracts.observation import Observation
from services.observation_publisher import publish_observation
from core.boundary.cost_calculator import CostCalculator

log = logging.getLogger("services.cost_anomaly_detector")


# ─────────────────────────────────────────────────────────────────────────────
# Fail-fast env var resolution (no fallback defaults — project lock)
# ─────────────────────────────────────────────────────────────────────────────

def _required(key: str) -> str:
    """Return env var value or raise RuntimeError. No fallback defaults."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast "
            f"(env-driven-no-fallbacks lock, Phase 74)"
        )
    return v


# Resolved at module import time — misconfiguration surfaces immediately.
MULT_INFO: float = 1.5  # Hardcoded; INFO is a panel-only signal, no channel notification
MULT_WARNING: float = float(_required("COST_ANOMALY_MULTIPLIER_WARN"))
MULT_CRITICAL: float = float(_required("COST_ANOMALY_MULTIPLIER_CRITICAL"))

# Conv-type display names for human-readable observation bodies (CONTEXT §11 lock)
_CONV_TYPE_DISPLAY: dict[str, str] = {
    "pre-trade": "Pre-Trade AI",
    "execution": "Execution AI",
    "macro": "Macro AI",
    "research": "Research AI",
    "strategy": "Strategy AI",
    "reflection": "Reflection AI",
}


class CostAnomalyDetector:
    """Deterministic rolling-average cost anomaly detector.

    Parameters
    ----------
    cost_calc:
        A ``CostCalculator`` instance with a populated ``_cost_ledger`` or
        production data source. The detector queries
        ``rolling_7d_avg_same_hour(conv_type, target_dt)`` to obtain the
        baseline for comparison.

    Usage
    -----
    ::

        detector = CostAnomalyDetector(cost_calc)
        obs = detector.evaluate("research", current_hour_cost=1.50, now=dt)
        # obs.severity == "INFO"  (1.5× avg)

    All emitted observations are published via ``publish_observation`` to the
    ``vm107.observations`` Redis channel for VM100's relay (Plan 03).
    """

    def __init__(self, cost_calc: CostCalculator) -> None:
        self._calc = cost_calc

    def evaluate(
        self,
        conv_type: str,
        current_hour_cost: float,
        now: Optional[datetime] = None,
    ) -> Optional[Observation]:
        """Evaluate cost anomaly for a conversation type and emit if thresholds crossed.

        Parameters
        ----------
        conv_type:
            Conversation type identifier (e.g. ``"research"``, ``"execution"``).
        current_hour_cost:
            Actual cost in USD for the current hour window for this conv_type.
        now:
            UTC datetime used as the reference point for the rolling-average
            query and as ``generated_at`` on the emitted Observation.  Defaults
            to ``datetime.now(timezone.utc)``.  Always pass explicitly in tests
            for full determinism.

        Returns
        -------
        Observation or None
            The emitted Observation, or ``None`` if current cost is within
            normal range (below 1.5× rolling avg).  Cold-start always returns
            an INFO Observation (never None — visibility is retained).
        """
        now = now or datetime.now(timezone.utc)
        rolling_avg = self._calc.rolling_7d_avg_same_hour(conv_type, now)

        # Cold-start guard (RESEARCH Pitfall 5)
        # rolling_avg == 0.0 means < 7 days of history for this conv_type+hour.
        # We emit INFO only — never WARNING/CRITICAL without a reliable baseline.
        if rolling_avg == 0.0:
            return self._emit(
                conv_type=conv_type,
                severity="INFO",
                body=f"Baseline not yet established for {conv_type}",
                now=now,
            )

        ratio = current_hour_cost / rolling_avg

        if ratio >= MULT_CRITICAL:
            severity = "CRITICAL"
        elif ratio >= MULT_WARNING:
            severity = "WARNING"
        elif ratio >= MULT_INFO:
            severity = "INFO"
        else:
            return None  # Within normal range — no observation

        return self._emit(
            conv_type=conv_type,
            severity=severity,
            body=self._format_body(conv_type, ratio),
            now=now,
        )

    def recover(
        self,
        correlation_id: str,
        conv_type: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Observation:
        """Emit a recovery INFO observation for an anomaly correlation chain (WORM).

        Recovery from an anomaly is a NEW observation with the same
        ``correlation_id`` — never an UPDATE to the spike observation.
        This preserves the append-only (WORM) observation log for behavioral
        analytics ("how long did the anomaly last?").

        Parameters
        ----------
        correlation_id:
            The ``correlation_id`` from the spike observation to correlate with.
        conv_type:
            Optional conversation type for context in the body.
        now:
            UTC reference time. Defaults to ``datetime.now(timezone.utc)``.

        Returns
        -------
        Observation
            A new INFO Observation with the same ``correlation_id``.
        """
        now = now or datetime.now(timezone.utc)
        conv_label = _CONV_TYPE_DISPLAY.get(conv_type or "", conv_type or "AI") if conv_type else "AI"
        return self._emit(
            conv_type=conv_type,
            severity="INFO",
            body=f"{conv_label} spend returned to normal",
            now=now,
            correlation_id=correlation_id,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _emit(
        self,
        conv_type: Optional[str],
        severity: str,
        body: str,
        now: datetime,
        correlation_id: Optional[str] = None,
    ) -> Observation:
        """Construct, publish, and return an Observation."""
        obs = Observation(
            category="cost_anomaly",
            severity=severity,
            body=body,
            generated_at=now,
            source_vm="VM107",
            trigger_event_id=f"cost_check_{conv_type}_{now.isoformat()}",
            correlation_id=correlation_id,
            trading_impact=False,  # cost anomaly never blocks trading (CONTEXT §22)
            conversation_type=conv_type,
        )
        publish_observation(obs)
        return obs

    @staticmethod
    def _format_body(conv_type: str, ratio: float) -> str:
        """Build a conversation-type-aware body string (CONTEXT §11 lock).

        Example: "Research AI spend is 4.2× above normal"
        NOT: "Cost anomaly detected"
        """
        display = _CONV_TYPE_DISPLAY.get(conv_type, conv_type.title())
        return f"{display} spend is {ratio:.1f}× above normal"
