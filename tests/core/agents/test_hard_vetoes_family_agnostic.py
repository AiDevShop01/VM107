"""Phase 48 Plan 48-04 Task 4.3 — hard vetoes are FAMILY-AGNOSTIC.

Implements REQ-48-D9. CONTEXT § Decision 9:
"Vetoes are family-agnostic (universal catastrophic viability constraints).
Family nuance is Critic skill responsibility."

The same 4 veto thresholds apply to all 5 strategy families. A backtest that
trips max_drawdown > 0.35 in a BREAKOUT strategy ALSO trips it in a
MEAN_REVERSION / TREND_CONTINUATION / AUCTION_ROTATION / VOLATILITY_EXPANSION
strategy — there is no per-family relaxation or tightening at the veto layer.

The check_hard_vetoes pure function takes only a BacktestResult, NOT a
StrategySpec or a StrategyFamily — by construction, family cannot influence
the output. This test asserts both:

  (a) the function signature contains only BacktestResult (no family param)
  (b) executing the same backtest across 5 simulated family contexts produces
      identical veto lists
"""
from __future__ import annotations

import inspect

import pytest

from core.contracts.schemas import (
    BacktestMetrics,
    BacktestResult,
    StrategyFamily,
)


def _vetoing_backtest() -> BacktestResult:
    """Backtest that trips ALL 4 vetoes simultaneously — the universal probe."""
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.20,            # < 0.30 -> veto
            rr=1.0,
            max_drawdown=0.42,        # > 0.35 -> veto
            profit_factor=1.6,
            consecutive_losses=15,    # > 10 -> veto
            regime_coverage=0.10,     # < 0.20 -> veto
        ),
        sample_size=250,
        confidence=0.6,
    )


# ---------------------------------------------------------------------------
# Signature inspection: function must NOT accept a family parameter.
# ---------------------------------------------------------------------------


def test_check_hard_vetoes_signature_has_no_family_parameter():
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    sig = inspect.signature(check_hard_vetoes)
    param_names = set(sig.parameters.keys())

    forbidden_param_names = {"family", "strategy_family", "spec", "strategy_spec"}
    overlap = param_names & forbidden_param_names
    assert not overlap, (
        f"check_hard_vetoes must be family-agnostic but signature includes: {overlap}"
    )


# ---------------------------------------------------------------------------
# Parametrized invariance: identical output across all 5 strategy families.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    [
        StrategyFamily.BREAKOUT,
        StrategyFamily.MEAN_REVERSION,
        StrategyFamily.TREND_CONTINUATION,
        StrategyFamily.AUCTION_ROTATION,
        StrategyFamily.VOLATILITY_EXPANSION,
    ],
)
def test_check_hard_vetoes_output_invariant_across_strategy_families(family):
    """Output is the same for every family, given the same backtest.

    This is a parametrized fixed-point check: family is supplied as part of
    the test name only — the production function CANNOT see it, so the output
    is invariant by construction. The test makes that invariance explicit.
    """
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    backtest = _vetoing_backtest()
    triggers = check_hard_vetoes(backtest)

    # All 4 vetoes fire regardless of family.
    metrics_triggered = {t["metric"] for t in triggers}
    assert metrics_triggered == {
        "max_drawdown",
        "win_rate",
        "consecutive_losses",
        "regime_coverage",
    }, f"family={family} should not change which vetoes fire"


def test_all_five_families_produce_identical_veto_lists_for_same_backtest():
    """Cross-family equality (not just per-family fixed shape).

    Build the veto list once per family; assert each subsequent list equals
    the first one structurally (same length, same metrics, same thresholds,
    same actuals).
    """
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    backtest = _vetoing_backtest()
    families = [
        StrategyFamily.BREAKOUT,
        StrategyFamily.MEAN_REVERSION,
        StrategyFamily.TREND_CONTINUATION,
        StrategyFamily.AUCTION_ROTATION,
        StrategyFamily.VOLATILITY_EXPANSION,
    ]
    # The family value never leaves this loop — by construction, check_hard_vetoes
    # cannot consume it. The assertion is purely an explicit invariance check.
    triggers_per_family = [check_hard_vetoes(backtest) for _ in families]

    canonical = triggers_per_family[0]
    for i, family in enumerate(families[1:], start=1):
        assert triggers_per_family[i] == canonical, (
            f"family={family} produced a divergent veto list — vetoes must be "
            "family-agnostic"
        )


def test_clean_backtest_returns_empty_for_every_family():
    """The negative side of the invariance — empty list is also family-agnostic."""
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    clean = BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.55,
            rr=1.5,
            max_drawdown=0.10,
            profit_factor=1.6,
            consecutive_losses=0,
            regime_coverage=1.0,
        ),
        sample_size=250,
        confidence=0.6,
    )

    for family in StrategyFamily:
        triggers = check_hard_vetoes(clean)
        assert triggers == [], (
            f"clean backtest must not trigger any vetoes — family={family}"
        )
