"""Phase 48 deterministic hard-veto checker.

PURE FUNCTION. No Mongo. No LLM. No Phase 56. No registry. Inputs in, list
of veto-trigger dicts out. Plan 05 (main loop) calls this BEFORE invoking
run_critic on every iteration; Plan 08b's main_loop wires it.

Implements REQ-48-D9. CONTEXT § Decision 9:
- "Universal, domain-agnostic, deterministic Python constants. Executed
   BEFORE Critic LLM ever runs."
- 4 catastrophic-only veto rules (LOCKED — NEVER refined):
   * max_drawdown > 0.35
   * win_rate < 0.30
   * consecutive_losses > 10
   * regime_coverage < 0.20
- "Critic NEVER overrides vetoes (orchestrator authority is absolute)."
- "Vetoes are family-agnostic (universal catastrophic viability constraints).
   Family nuance is Critic skill responsibility."

Veto layer is search-space pruning — answers "Should this search continue
at all?" — not "Is this strategy promising?" (that's Critic territory).
"""
from __future__ import annotations

from typing import Any

from core.agents.refinement_orchestrator.policy_constants import HARD_VETOES
from core.contracts.schemas import BacktestResult


def _compare(op: str, actual: float | int, threshold: float | int) -> bool:
    """Tiny operator dispatcher. The veto policy uses only ``>`` and ``<``."""
    if op == ">":
        return actual > threshold
    if op == "<":
        return actual < threshold
    raise ValueError(f"Unsupported veto op: {op!r}")


def _read_metric(backtest_result: BacktestResult, metric: str) -> float | int:
    """Extract a metric value from a BacktestResult.

    sample_size lives at the top level; everything else lives on
    BacktestResult.metrics. (sample_size isn't a veto metric in V1, but the
    extraction pattern is shared with acceptance_floor for consistency.)
    """
    if metric == "sample_size":
        return backtest_result.sample_size
    return getattr(backtest_result.metrics, metric)


def check_hard_vetoes(backtest_result: BacktestResult) -> list[dict[str, Any]]:
    """Evaluate all 4 hard vetoes against a BacktestResult.

    Family-agnostic by construction: the signature accepts ONLY a
    BacktestResult — no StrategySpec, no StrategyFamily. Critic skill
    overlays handle per-family nuance at a different layer.

    Args:
        backtest_result: typed Phase 45+ BacktestResult. Must include
            metrics.consecutive_losses and metrics.regime_coverage (Plan 48-04
            extended BacktestMetrics with additive default fields so pre-Phase-48
            callers stay below-veto / above-veto without code change).

    Returns:
        List of triggered-veto dicts (empty list when nothing trips):
            [{"metric": str, "threshold": float|int, "actual": float|int,
              "op": str}, ...]
        One entry per triggered veto rule; iteration order matches HARD_VETOES
        dict insertion order (Python 3.7+ guarantees insertion ordering).
    """
    triggers: list[dict[str, Any]] = []
    for metric, rule in HARD_VETOES.items():
        op: str = rule["op"]  # type: ignore[assignment]
        threshold: float | int = rule["value"]  # type: ignore[assignment]
        actual = _read_metric(backtest_result, metric)
        if _compare(op, actual, threshold):
            triggers.append(
                {
                    "metric": metric,
                    "threshold": threshold,
                    "actual": actual,
                    "op": op,
                }
            )
    return triggers


__all__ = ["check_hard_vetoes"]
