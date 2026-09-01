"""Phase 91 Plan 3 Task 2 — MacroLiquidityMonitor agent.

Computes a 0..100 global_liquidity_score from substrate inputs and emits
alert_candidate envelopes (alert_type='liquidity') when the score crosses
thresholds:

  - score < 20            → 'blocking' (Critical)
  - 20 <= score < 30      → 'warning' (Important)
  - score drops > 15 pts vs prev → emit even when curr > 30

Status experimental: Phase 86 substrate is incomplete; ``compute_liquidity_score``
returns None for empty input and the agent emits nothing. As Phase 86 lands
more signals, the score becomes more reliable + the agent_profile status
can be promoted to 'real'.

Substrate keys consumed (all optional — score reflects the subset available):

  - credit_spreads_widened : bool   (True → -25)
  - funding_stress_index   : float  (0..1, contributes weighted)
  - dxy_spike_24h          : float  (% change, contributes weighted)

Pattern mirrors ``agents.macro_indicator_alert_emitter.MacroIndicatorAlertEmitter``
for the agent surface; uses ``core/alerts/phase91_emit.emit_alert_candidate``
for the actual fan-out.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from core.alerts.phase91_emit import emit_alert_candidate

from .contract import LiquidityScore

logger = logging.getLogger(__name__)


_PRODUCER_AGENT_ID = "vm107.macro_liquidity_monitor"
_SUBJECT_ID = "global_liquidity_score"

# Score thresholds — kept here so tests + emit logic share a single source
_BLOCKING_THRESHOLD = 20    # score < this → critical
_WARNING_THRESHOLD = 30     # score < this → warning
_DROP_THRESHOLD = 15        # |prev - curr| > this → emit even when curr above WARNING


def compute_liquidity_score(substrate: dict[str, Any]) -> float | None:
    """Compute 0..100 score from substrate.

    Returns:
        Float score [0..100] when at least one substrate key is present;
        None when substrate is empty (status=experimental degraded mode —
        Phase 86 substrate hasn't shipped enough signal yet).
    """
    if not substrate:
        return None

    # Start at 100 (perfect liquidity) and subtract per stress signal present.
    score = 100.0
    contributed = False

    if "credit_spreads_widened" in substrate:
        contributed = True
        if bool(substrate["credit_spreads_widened"]):
            score -= 25.0

    fsi = substrate.get("funding_stress_index")
    if isinstance(fsi, (int, float)):
        contributed = True
        # funding_stress_index ∈ [0..1] — weight 50 points
        score -= 50.0 * max(0.0, min(1.0, float(fsi)))

    dxy_spike = substrate.get("dxy_spike_24h")
    if isinstance(dxy_spike, (int, float)):
        contributed = True
        # dxy_spike_24h is a % change; clamp to [0..3] and weight 25 points
        clamped = max(0.0, min(3.0, float(dxy_spike)))
        score -= (25.0 / 3.0) * clamped

    if not contributed:
        return None

    return max(0.0, min(100.0, score))


# Recognised substrate signal keys — provenance source for the typed contract.
# Mirrors (does NOT alter) the contribution logic in ``compute_liquidity_score``.
_SIGNAL_KEYS = ("credit_spreads_widened", "funding_stress_index", "dxy_spike_24h")


def _contributing_keys(substrate: dict[str, Any]) -> list[str]:
    """Return the substrate keys that contributed to the score (provenance).

    Matches ``compute_liquidity_score`` exactly: ``credit_spreads_widened`` when
    present; the two numeric signals when they are int/float. Empty when nothing
    contributed (degraded).
    """
    keys: list[str] = []
    if "credit_spreads_widened" in substrate:
        keys.append("credit_spreads_widened")
    if isinstance(substrate.get("funding_stress_index"), (int, float)):
        keys.append("funding_stress_index")
    if isinstance(substrate.get("dxy_spike_24h"), (int, float)):
        keys.append("dxy_spike_24h")
    return keys


def _tier_for(score: float | None) -> str | None:
    """Map a score to its threshold tier using the single-source constants.

    None → None (honest-null: no tier asserted on degraded substrate).
    """
    if score is None:
        return None
    if score < _BLOCKING_THRESHOLD:
        return "blocking"
    if score < _WARNING_THRESHOLD:
        return "warning"
    return "normal"


def score_liquidity(substrate: dict[str, Any]) -> LiquidityScore:
    """Typed boundary over ``compute_liquidity_score``.

    Wraps the EXISTING deterministic scorer in a :class:`LiquidityScore`,
    preserving honest-null semantics: an empty / non-contributing substrate
    yields ``score=None, degraded=True, tier=None`` — NEVER coerced to 0. The
    thresholds, ``_should_emit`` and the ``emit_alert_candidate`` fan-out are
    untouched by this wrapper.
    """
    score = compute_liquidity_score(substrate)
    return LiquidityScore(
        score=score,
        tier=_tier_for(score),
        substrate_keys_present=_contributing_keys(substrate),
        computed_at=datetime.now(tz=timezone.utc),
        producer_agent_id=_PRODUCER_AGENT_ID,
        degraded=(score is None),
    )


def _event_id_for(score: float, ts_iso: str) -> str:
    raw = f"{_PRODUCER_AGENT_ID}|{_SUBJECT_ID}|{score:.2f}|{ts_iso}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _should_emit(score: float | None, prev_score: float | None) -> bool:
    if score is None:
        return False
    if score < _WARNING_THRESHOLD:
        return True
    if prev_score is not None and (prev_score - score) > _DROP_THRESHOLD:
        return True
    return False


def _b13_severity_for(score: float) -> str:
    return "blocking" if score < _BLOCKING_THRESHOLD else "warning"


class MacroLiquidityMonitor:
    """Compute global_liquidity_score + emit alert_candidate on threshold breach.

    Stateless — every call to ``run_once`` reads the substrate fresh + emits
    if appropriate. The Dagster sensor or operator-triggered invoke is the
    sole caller.
    """

    agent_id: str = _PRODUCER_AGENT_ID

    def compute_liquidity_score(self, substrate: dict[str, Any]) -> float | None:
        """Delegate to module-level helper — kept on the class for DI clarity."""
        return compute_liquidity_score(substrate)

    def emit_for_score(
        self,
        score: float,
        components: dict[str, Any],
        *,
        prev_score: float | None = None,
    ) -> bool:
        """Emit an alert_candidate envelope when ``score`` crosses thresholds.

        Returns:
            True when an envelope was emitted, False otherwise.
        """
        if not _should_emit(score, prev_score):
            return False

        b13_severity = _b13_severity_for(score)
        ts_iso = datetime.now(tz=timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "liquidity_score": score,
            "prev_liquidity_score": prev_score,
            "stress_components": dict(components or {}),
        }
        explanation = (
            f"Global liquidity score {score:.0f}"
            + (f" (was {prev_score:.0f})" if prev_score is not None else "")
        )
        event_id = _event_id_for(score, ts_iso)

        try:
            emit_alert_candidate(
                alert_type="liquidity",
                producer_agent_id=_PRODUCER_AGENT_ID,
                subject_type="indicator",
                subject_id=_SUBJECT_ID,
                b13_internal_severity=b13_severity,
                explanation=explanation,
                citations=[f"vm107://liquidity_monitor/score/{ts_iso[:10]}"],
                confidence=0.85,
                event_id=event_id,
                extra_payload=payload,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error({
                "event": "liquidity_alert_emit_failed",
                "score": score,
                "prev_score": prev_score,
                "error": str(exc),
            })
            return False

    def run_once(
        self,
        substrate: dict[str, Any],
        *,
        prev_score: float | None = None,
    ) -> dict[str, Any]:
        """Compute → maybe emit. Returns a stats dict the caller can log."""
        score = self.compute_liquidity_score(substrate)
        emitted = False
        if score is not None:
            components = {
                k: v for k, v in substrate.items()
                if k in ("credit_spreads_widened", "funding_stress_index", "dxy_spike_24h")
            }
            emitted = self.emit_for_score(score, components, prev_score=prev_score)

        return {
            "agent_id": self.agent_id,
            "score": score,
            "prev_score": prev_score,
            "emitted": emitted,
        }


__all__ = [
    "MacroLiquidityMonitor",
    "compute_liquidity_score",
    "score_liquidity",
    "LiquidityScore",
]
