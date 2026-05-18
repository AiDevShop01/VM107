"""Phase 48 deterministic acceptance-floor classifier.

PURE FUNCTION. No Mongo. No LLM. No Phase 56. No registry. Inputs in,
DeterministicAcceptanceResult out. Plan 05 (main loop) calls this BEFORE
invoking run_critic on every iteration; Plan 08b's main_loop wires it.

Implements REQ-48-D8. CONTEXT § Decision 8:
- "Below floor -> Python forces REFINE or REJECT BEFORE Critic LLM executes
   (preserves cognition budget)."
- 4 floor metrics: sample_size >= 200, win_rate >= 0.45, max_drawdown <= 0.20,
   profit_factor >= 1.2 (Phase 46 ROADMAP V1 numbers).
- Severity policy (ACCEPT_FLOOR_BREACH_THRESHOLD=0.20):
   * breach > 20% -> HARD_REJECT
   * breach <= 20% -> REFINABLE_WEAKNESS
   * mixed -> HARD_REJECT (worst-case wins)
   * all pass -> CRITIC_ELIGIBLE

Layering vs Phase 45 validity floor + Critic verdict:
  Phase 45 validity floor  -> "Is the backtest valid?"
  Phase 48 acceptance floor -> "Is this strategy worth refining further?"
  Critic verdict            -> "Is this strategy strategically promising?"
"""
from __future__ import annotations

from typing import Any

from core.agents.refinement_orchestrator.policy_constants import (
    ACCEPT_FLOOR_BREACH_THRESHOLD,
    ACCEPT_FLOORS,
)
from core.contracts.schemas import (
    AcceptanceClassification,
    BacktestResult,
    DeterministicAcceptanceResult,
)


def _breach_pct(metric: str, actual: float) -> float:
    """Return the fractional breach magnitude for `metric` against ACCEPT_FLOORS.

    For floor metrics (sample_size, win_rate, profit_factor):
        breach = (floor - actual) / floor   when actual < floor; else 0.0
    For ceiling metrics (max_drawdown):
        breach = (actual - ceiling) / ceiling   when actual > ceiling; else 0.0
    """
    threshold = ACCEPT_FLOORS[metric]
    if metric == "max_drawdown":
        # Ceiling: failure is OVER the threshold.
        if actual <= threshold:
            return 0.0
        return (actual - threshold) / threshold
    # Floor: failure is UNDER the threshold.
    if actual >= threshold:
        return 0.0
    return (threshold - actual) / threshold


def _extract_metrics(backtest_result: BacktestResult) -> dict[str, Any]:
    """Pull the 4 floor metrics from the typed BacktestResult.

    sample_size is top-level on BacktestResult; the other 3 live on
    BacktestResult.metrics. Returns a plain dict for the breach computation
    + the metrics_snapshot field.
    """
    m = backtest_result.metrics
    return {
        "sample_size": backtest_result.sample_size,
        "win_rate": m.win_rate,
        "max_drawdown": m.max_drawdown,
        "profit_factor": m.profit_factor,
    }


def classify_acceptance(
    backtest_result: BacktestResult,
) -> DeterministicAcceptanceResult:
    """Classify a BacktestResult against the 4 acceptance floors.

    Pure: same inputs always produce same outputs; no side effects.

    Args:
        backtest_result: typed Phase 45+ BacktestResult. Must include
            metrics.profit_factor (Plan 48-04 extended BacktestMetrics with
            an additive default-999.0 field so pre-Phase-48 callers stay
            above-floor without code change).

    Returns:
        DeterministicAcceptanceResult with:
            - classification in {HARD_REJECT, REFINABLE_WEAKNESS, CRITIC_ELIGIBLE}
            - passed = True iff classification == CRITIC_ELIGIBLE
            - failed_constraints = list of every breached metric (mild + hard)
            - metrics_snapshot = {4 raw metrics, derived_breach_pct_per_metric}
            - schema_version = 1
    """
    metrics = _extract_metrics(backtest_result)

    breach_pct: dict[str, float] = {
        name: _breach_pct(name, float(actual))
        for name, actual in metrics.items()
    }

    failed_constraints = [name for name, bp in breach_pct.items() if bp > 0.0]
    any_hard_breach = any(
        bp > ACCEPT_FLOOR_BREACH_THRESHOLD for bp in breach_pct.values()
    )

    if not failed_constraints:
        classification = AcceptanceClassification.CRITIC_ELIGIBLE
    elif any_hard_breach:
        # Worst-case wins: a single >20% breach drives the verdict to HARD_REJECT
        # even if other breaches are mild.
        classification = AcceptanceClassification.HARD_REJECT
    else:
        classification = AcceptanceClassification.REFINABLE_WEAKNESS

    snapshot = dict(metrics)
    snapshot["derived_breach_pct_per_metric"] = breach_pct

    return DeterministicAcceptanceResult(
        passed=(classification == AcceptanceClassification.CRITIC_ELIGIBLE),
        failed_constraints=failed_constraints,
        metrics_snapshot=snapshot,
        classification=classification,
        schema_version=1,
    )


__all__ = ["classify_acceptance"]
