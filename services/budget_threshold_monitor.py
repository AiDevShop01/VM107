"""Budget threshold monitor (Phase 74 REQ-74-7 + CONTEXT §22).

Emits cost_anomaly Observation at 80% / 100% / 120% of DAILY_AI_BUDGET_USD.
At 120%, invokes router tier-down for NON-TRADE-PATH conv-types only.

CONTEXT §22 locks:
- NEVER hard-cut AI calls at any threshold (AI never blocks trading)
- Trade-path conv-types (pre-trade/execution/macro) NEVER tier-down or block
- All threshold crossings emit Observations (visibility) + flow through NotificationRule

Threshold-crossing semantics (NOT threshold-at semantics):
- Each threshold fires at most once per calendar day
- Re-evaluation at the same or higher percentage within the same day does NOT re-emit
- Day rollover resets the crossing state

Anti-patterns (NEVER):
    - Blocking AI calls at 100% or any threshold (CONTEXT §22 lock)
    - Including trade-path types in tier_down_for_overage() call
    - Re-emitting threshold observations within the same day
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone, date
from typing import Optional

from fingpt_core.contracts.observation import Observation
from services.observation_publisher import publish_observation

log = logging.getLogger("services.budget_threshold_monitor")


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


DAILY_BUDGET_USD: float = float(_required("DAILY_AI_BUDGET_USD"))


# ─────────────────────────────────────────────────────────────────────────────
# Conversation type partition (CONTEXT §22 + REQ-74-7 lock)
# ─────────────────────────────────────────────────────────────────────────────

TRADE_PATH_CONV_TYPES: frozenset[str] = frozenset({"pre-trade", "execution", "macro"})
NON_TRADE_PATH_CONV_TYPES: frozenset[str] = frozenset({"research", "strategy", "reflection"})

# Budget threshold ratios
THRESHOLDS: dict[str, float] = {
    "warning": 0.80,    # 80%  → System channel WARNING (P2) — CONTEXT §22
    "critical": 1.00,   # 100% → System channel CRITICAL (P1) — CONTEXT §22
    "tier_down": 1.20,  # 120% → CRITICAL + router tier-down (non-trade-path only)
}

# Threshold evaluation order: highest first, so the most important event fires
# (lower thresholds are already crossed when higher ones are hit)
_THRESHOLD_ORDER = ("tier_down", "critical", "warning")


class BudgetThresholdMonitor:
    """Daily AI budget threshold crossing detector.

    Emits ``cost_anomaly`` Observations at 80% / 100% / 120% of
    ``DAILY_AI_BUDGET_USD``.  At 120%, also calls
    ``router.tier_down_for_overage(NON_TRADE_PATH_CONV_TYPES)`` to downgrade
    non-critical AI conversation types to cheaper fallback models.

    Parameters
    ----------
    router:
        The ``ModelRouter`` instance to invoke at 120%.  Must implement
        ``tier_down_for_overage(conv_types: frozenset[str])``.

    Notes
    -----
    State (``_crossed_today``) is in-process and resets on day rollover.
    Multi-instance deployments will have independent state per instance; a
    Redis-backed crossing state is the v2 upgrade path.
    """

    def __init__(self, router) -> None:
        self._router = router
        # threshold_name → calendar date on which it was crossed
        self._crossed_today: dict[str, date] = {}

    def evaluate(
        self,
        spent_today_usd: float,
        now: Optional[datetime] = None,
    ) -> Optional[Observation]:
        """Evaluate budget spend against thresholds and emit crossing observations.

        Parameters
        ----------
        spent_today_usd:
            Total USD spent today across all conversation types.
        now:
            Reference UTC datetime.  Defaults to ``datetime.now(timezone.utc)``.
            Always pass explicitly in tests for full determinism.

        Returns
        -------
        Observation or None
            The first NEW threshold crossing observation (highest threshold
            crossed that hasn't fired today), or ``None`` if no new crossing.

        Notes
        -----
        Only one observation is returned per call (the highest new crossing).
        Multiple thresholds may logically be crossed in a single call (e.g.,
        jumping from 70% to 125% crosses both 80% and 100% and 120%).  In that
        case the highest (120%) fires; the lower ones are implicitly marked as
        already-crossed for the day so they don't fire on subsequent calls.
        """
        now = now or datetime.now(timezone.utc)
        today = now.date()

        # Purge stale crossing records from previous days
        self._crossed_today = {k: v for k, v in self._crossed_today.items() if v == today}

        pct = spent_today_usd / DAILY_BUDGET_USD if DAILY_BUDGET_USD > 0 else 0.0

        for threshold_name in _THRESHOLD_ORDER:
            t = THRESHOLDS[threshold_name]
            already_crossed_today = self._crossed_today.get(threshold_name) == today

            if pct >= t and not already_crossed_today:
                # Mark this threshold (and all lower ones) as crossed today
                for tn, tv in THRESHOLDS.items():
                    if tv <= t:
                        self._crossed_today[tn] = today

                # At 120%: invoke router tier-down for non-trade-path types
                if threshold_name == "tier_down":
                    self._router.tier_down_for_overage(NON_TRADE_PATH_CONV_TYPES)

                severity = "CRITICAL" if threshold_name in ("critical", "tier_down") else "WARNING"
                obs = Observation(
                    category="cost_anomaly",
                    severity=severity,
                    body=f"Daily AI budget at {int(pct * 100)}% (threshold: {threshold_name})",
                    generated_at=now,
                    source_vm="VM107",
                    trigger_event_id=(
                        f"budget_threshold_crossed_{threshold_name}_{today.isoformat()}"
                    ),
                    correlation_id=f"budget_{today.isoformat()}",
                    trading_impact=False,  # never hard-cuts trading (CONTEXT §22 lock)
                    conversation_type=None,
                )
                publish_observation(obs)
                return obs

        return None
