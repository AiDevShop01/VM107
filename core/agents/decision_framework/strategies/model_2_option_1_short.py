"""Phase 47.3 Plan 05 — Model 2 Option 1 Short strategy overrides + hard-reject predicates.

Module-level imports trigger registration via ``@register_override`` and
``@register_hard_reject`` decorators. The ``strategies/__init__.py``
package-init imports this module for its registration side-effect during
``Framework()`` boot.

Strategy YAML: ``VM107/agents/agent0/strategies/model_2_option_1_short.yaml``
  - 5 criteria (HTF trend alignment, compression, displacement, continuation,
    liquidity sweep)
  - 3 hard_rejects: ``breakout into HVN`` · ``no displacement`` ·
    ``against HTF trend``

CF-3 conservative read (LOCKED in CONTEXT decision 5 + RESEARCH OQ-7):
  Hard-reject predicates that depend on category data MUST conservatively
  return True when the underlying CategoryResult is ``not_available``. We
  cannot confirm the disqualifying invariant is absent — safety bias is
  better than executing on partial data.

OQ-6 (predicate name → Python function naming):
  YAML uses spaces in hard_reject names (matches the ``HardReject.name``
  field literally). The Python function names use underscore-snake-case for
  PEP 8. Decorators bind YAML name → Python callable so the boot-time
  assertion sees ``("model_2_option_1_short", "no displacement")`` etc.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..category_evaluators import _peak_body_atr_ratio
from ..context import EvaluationContext
from ..hard_rejects import register_hard_reject
from ..overrides import CategoryWeight, register_override
from ..thresholds import DISPLACEMENT_BODY_ATR_STRONG

if TYPE_CHECKING:
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

log = logging.getLogger(__name__)

STRATEGY_ID = "model_2_option_1_short"


# === Overrides ===========================================================


@register_override(STRATEGY_ID, "Location")
def location_secondary_when_momentum_strong(
    ctx: EvaluationContext,
) -> CategoryWeight:
    """CONTEXT decision 3 example: Location weight halved (10 → 5) when
    M5 momentum displacement is strong.

    Rationale: Model 2 Option 1 Short is a momentum-continuation strategy.
    When displacement is unambiguous, the entry's exact location within the
    M15 swing range matters less — the move is already in progress. Halving
    the Location max_points reflects this priority shift; the Location
    evaluator's status (pass/fail/unclear/not_available) is unchanged
    (LOCK 3 — overrides modify weight/thresholds, never status).

    Note (Risk 5 mitigation): This override resolves BEFORE the Momentum
    evaluator runs, so it cannot peek at the Momentum CategoryResult.
    Instead, it inlines the same body/ATR ratio check via the shared
    ``_peak_body_atr_ratio`` helper which the Momentum evaluator also uses,
    keeping the threshold semantics consistent across both call sites.

    Default behavior (uncertain signal): when M5 primitives are missing or
    the L1 layer carries no usable atr_short, return weight_multiplier=1.0
    (no weight reduction on inconclusive data).
    """
    m5 = ctx.primitives_m5
    if m5 is None or m5.status != "ok" or m5.data is None:
        return CategoryWeight(weight_multiplier=1.0)

    layers = m5.data.layers or []
    layer1 = next((lb for lb in layers if getattr(lb, "layer", None) == 1), None)
    if layer1 is None or getattr(layer1, "count", 0) == 0:
        return CategoryWeight(weight_multiplier=1.0)

    peak = _peak_body_atr_ratio(getattr(layer1, "bars", []) or [])
    if peak is not None and peak > DISPLACEMENT_BODY_ATR_STRONG:
        return CategoryWeight(
            weight_multiplier=0.5,
            note=(
                f"momentum strong (peak body/atr={peak:.2f} > "
                f"{DISPLACEMENT_BODY_ATR_STRONG}); location secondary"
            ),
        )
    return CategoryWeight(weight_multiplier=1.0)


# === Hard-reject predicates (CF-3 conservative read) =====================


def _category_status(
    by_name: "dict[str, CategoryResult]", category: str
) -> Optional[str]:
    """Return the status of ``category`` in ``by_name``, or None if absent.

    Defensive helper — predicates dispatch BEFORE evaluators in some test
    paths (e.g., direct ``_HARD_REJECTS[...](None, by_name)`` calls). The
    by_name dict shape is the contract; absence is handled explicitly.
    """
    cat = by_name.get(category)
    return getattr(cat, "status", None) if cat is not None else None


@register_hard_reject(STRATEGY_ID, "no displacement")
def no_displacement(
    ctx: Optional[EvaluationContext], by_name: "dict[str, CategoryResult]"
) -> bool:
    """**CF-3 conservative read (safety bias).**

    Hard reject FIRES when Momentum is ``fail`` OR ``not_available``.

    Why ``not_available`` fires the reject (the load-bearing decision):
    - Hard rejects are pre-committed strategy invariants — "if this is true,
      this trade is invalid."
    - The Model 2 Option 1 Short setup REQUIRES displacement to be present.
    - When momentum data is missing, we CANNOT confirm the displacement
      invariant. Better to skip a real trade than execute one where the
      framework can't confirm.
    - The alternative read (only fire on ``fail`` with real data) would
      mean partial-context evaluations bypass hard rejects entirely — a
      worse failure mode than over-rejection.

    Returns False if Momentum is ``pass`` or ``unclear`` (the displacement
    invariant is at least partially confirmed) or if the Momentum result
    is absent from ``by_name`` (cannot reason — defer to other gates).
    """
    status = _category_status(by_name, "Momentum")
    return status in ("fail", "not_available")


@register_hard_reject(STRATEGY_ID, "against HTF trend")
def against_htf_trend(
    ctx: Optional[EvaluationContext], by_name: "dict[str, CategoryResult]"
) -> bool:
    """**CF-3 conservative read (safety bias).**

    Hard reject FIRES when HTF is ``fail`` OR ``not_available``.

    Symmetric with ``no_displacement``: HTF trend alignment is also a
    pre-committed invariant for Model 2 Option 1 Short. Missing HTF data
    means we cannot confirm the trade is WITH the higher-timeframe trend,
    so the reject fires (we can't disprove "against HTF").

    Returns False if HTF is ``pass`` or ``unclear`` (alignment at least
    partially confirmed) or if the HTF result is absent from ``by_name``.
    """
    status = _category_status(by_name, "HTF")
    return status in ("fail", "not_available")


@register_hard_reject(STRATEGY_ID, "breakout into HVN")
def breakout_into_hvn(
    ctx: Optional[EvaluationContext], by_name: "dict[str, CategoryResult]"
) -> bool:
    """**Honest stub — Phase 47.6+ will replace with real predicate.**

    HVN (High Volume Node from volume profile) data is not yet wired into
    ``EvaluationContext`` — Phase 30+ work has not surfaced volume profile
    in the typed Tier-2 envelope. V1 always returns False (cannot detect).

    Why register an honest stub instead of leaving it absent:
    - The boot-time assertion (Plan 03) requires every YAML hard_reject
      name to map to a registered predicate (CF-5). Leaving it unregistered
      would fail ``Framework()`` construction.
    - Silently skipping in ``detect_hard_rejects`` (without registration)
      would mask the gap. A registered always-False predicate makes the
      gap explicit in code review and traceable from this docstring.

    TODO Phase 47.6+ — flip to real predicate when HVN data lands in
    ``EvaluationContext.liquidity_*.data`` (or a new field).
    """
    # Liquidity result is not consulted in V1. Reference parameter to keep
    # signature uniform with the other predicates (no unused-arg warnings).
    _ = (ctx, by_name)
    return False
