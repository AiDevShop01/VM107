"""Phase 47.3 — Category evaluators (Plan 04).

9 deterministic Python functions, one per category. Each takes
``EvaluationContext`` and returns a ``CategoryResult`` with status
(pass/fail/unclear/not_available), score_contribution (0..max_points),
max_points (override-adjusted), threshold_used (human-readable note), and
override_applied (override note if any).

CONTEXT LOCK 1: LLM never decides any of these. Pure Python.
CONTEXT LOCK 3: Overrides modify WEIGHT (max_points) + THRESHOLDS but NEVER
flip status. Status is computed purely from data. ``safe_resolve_weight``
returns the override-aware max_points and a note; ``_resolve_override_thresholds``
returns the override-aware thresholds (default if the override left them None).
CONTEXT LOCK 4: ``not_available`` contributes 0 score; ``max_points`` stays at
its allocation (the gap shows up as a confidence dock, not a score rebalance).

``unclear`` always contributes 50% of ``max_points`` (rounded). V1 lock; Phase 49
may tune.

EVALUATOR_DISPATCH dict at module bottom maps category name → evaluator
callable in canonical CATEGORY_ORDER. Framework.run consumes it via lazy
late import.
"""

from __future__ import annotations

from typing import Callable, Optional

from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

from .context import EvaluationContext
from .overrides import resolve_override, safe_resolve_weight
from .thresholds import (
    COMPRESSION_MAX_POINTS,
    COMPRESSION_SCORE_PASS,
    COMPRESSION_SCORE_UNCLEAR,
    DISPLACEMENT_BODY_ATR_STRONG,
    DISPLACEMENT_BODY_ATR_WEAK,
    HTF_BOS_LOOKBACK,
    HTF_MAX_POINTS,
    LIQUIDITY_MAX_POINTS,
    LIQUIDITY_PROXIMITY_ATR_STRONG,
    LIQUIDITY_PROXIMITY_ATR_WEAK,
    LOCATION_MAX_POINTS,
    LOCATION_PREMIUM_PCT_STRONG,
    LOCATION_PREMIUM_PCT_WEAK,
    MOMENTUM_MAX_POINTS,
    NEWS_MAX_POINTS,
    PULLBACK_MAX_POINTS,
    PULLBACK_PROXIMITY_ATR_STRONG,
    PULLBACK_PROXIMITY_ATR_WEAK,
    RR_MAX_POINTS,
    RR_THRESHOLD_PASS,
    RR_THRESHOLD_UNCLEAR,
    STRUCTURE_BOS_LOOKBACK,
    STRUCTURE_MAX_POINTS,
)

# === Shared helpers (Risk 5 mitigation: extract from inline duplication) ===


def _peak_body_atr_ratio(
    layer1_bars: list, lookback: int = 10
) -> Optional[float]:
    """Compute peak body/ATR ratio from M5 L1 bars.

    Returns None if no bars carry a usable atr_short. Used by Momentum
    evaluator and (Plan 05) the Model 2 Option 1 Short Location override.
    """
    if not layer1_bars:
        return None
    recent = layer1_bars[-lookback:]
    ratios: list[float] = []
    for b in recent:
        atr = b.get("atr_short", 0) or 0
        if atr <= 0:
            continue
        body = abs((b.get("close", 0) or 0) - (b.get("open", 0) or 0))
        ratios.append(body / atr)
    return max(ratios) if ratios else None


def _resolve_override_thresholds(
    ctx: EvaluationContext,
    category_name: str,
    default_strong: float,
    default_weak: float,
) -> tuple[float, float, Optional[str]]:
    """Read override threshold values from a registered override callable.

    Returns ``(threshold_strong, threshold_weak, note)``. Falls back to
    defaults when:
      - No strategy attached.
      - No override registered for ``(strategy_id, category_name)``.
      - Override callable raises (note carries ``override_failed: <Type>``).
      - Override returned value but left thresholds as None.

    The resulting note is propagated into ``CategoryResult.override_applied``
    by the calling evaluator, so the trader sees the framework's discipline.
    """
    if not ctx.strategy_id:
        return default_strong, default_weak, None
    fn = resolve_override(ctx.strategy_id, category_name)
    if fn is None:
        return default_strong, default_weak, None
    try:
        spec = fn(ctx)
    except Exception as exc:  # noqa: BLE001
        return default_strong, default_weak, f"override_failed: {type(exc).__name__}"
    strong = (
        spec.threshold_strong
        if getattr(spec, "threshold_strong", None) is not None
        else default_strong
    )
    weak = (
        spec.threshold_weak
        if getattr(spec, "threshold_weak", None) is not None
        else default_weak
    )
    note = getattr(spec, "note", None)
    return strong, weak, note


def _get_atr_from_m5(ctx: EvaluationContext) -> Optional[float]:
    """Pull median atr_short from M5 L1 last 10 bars (or None when missing)."""
    if not ctx.primitives_m5 or ctx.primitives_m5.status != "ok":
        return None
    layers = getattr(ctx.primitives_m5.data, "layers", []) or []
    layer1 = next((lb for lb in layers if getattr(lb, "layer", None) == 1), None)
    if layer1 is None:
        return None
    bars = getattr(layer1, "bars", []) or []
    atrs = [b.get("atr_short") for b in bars[-10:] if b.get("atr_short")]
    if not atrs:
        return None
    sorted_atrs = sorted(atrs)
    return sorted_atrs[len(sorted_atrs) // 2]


def _combine_notes(*notes: Optional[str]) -> Optional[str]:
    """Combine non-empty override notes into a single ``;``-separated string."""
    parts = [n for n in notes if n]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return "; ".join(parts)


# === Evaluators ===


def evaluate_momentum(ctx: EvaluationContext) -> CategoryResult:
    """Momentum/Displacement (15 pts).

    pass: peak body/ATR > STRONG (1.5)
    unclear: in (WEAK, STRONG]
    fail: <= WEAK (1.0)
    not_available: M5 primitives missing or atr_short absent on all recent bars.
    """
    name = "Momentum"
    max_points, weight_note = safe_resolve_weight(
        ctx.strategy_id, name, ctx, MOMENTUM_MAX_POINTS
    )
    threshold_strong, threshold_weak, threshold_note = _resolve_override_thresholds(
        ctx, name, DISPLACEMENT_BODY_ATR_STRONG, DISPLACEMENT_BODY_ATR_WEAK
    )
    override_note = _combine_notes(weight_note, threshold_note)

    m5 = ctx.primitives_m5
    if m5 is None or m5.status == "not_available":
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="M5 primitives unavailable",
            override_applied=override_note,
        )

    layers = getattr(m5.data, "layers", []) or []
    layer1 = next((lb for lb in layers if getattr(lb, "layer", None) == 1), None)
    if layer1 is None or getattr(layer1, "count", 0) == 0:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="L1 absent in primitives",
            override_applied=override_note,
        )

    peak = _peak_body_atr_ratio(getattr(layer1, "bars", []) or [])
    if peak is None:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="atr_short missing on all recent bars",
            override_applied=override_note,
        )

    if peak > threshold_strong:
        return CategoryResult(
            name=name,
            status="pass",
            score_contribution=max_points,
            max_points=max_points,
            threshold_used=f"peak_body_atr={peak:.2f} > {threshold_strong}",
            override_applied=override_note,
        )
    if peak > threshold_weak:
        return CategoryResult(
            name=name,
            status="unclear",
            score_contribution=round(max_points * 0.5),
            max_points=max_points,
            threshold_used=f"peak_body_atr={peak:.2f} in ({threshold_weak},{threshold_strong}]",
            override_applied=override_note,
        )
    return CategoryResult(
        name=name,
        status="fail",
        score_contribution=0,
        max_points=max_points,
        threshold_used=f"peak_body_atr={peak:.2f} <= {threshold_weak}",
        override_applied=override_note,
    )


def evaluate_rr(ctx: EvaluationContext) -> CategoryResult:
    """RR (10 pts) — computed from journal entry/SL/TP. No capability dep.

    pass: planned_rr >= 1.5
    unclear: in [1.0, 1.5)
    fail: < 1.0
    not_available: entry/SL/TP missing in journal (or risk = 0).
    """
    name = "RR"
    max_points, weight_note = safe_resolve_weight(
        ctx.strategy_id, name, ctx, RR_MAX_POINTS
    )
    threshold_pass, threshold_unclear, t_note = _resolve_override_thresholds(
        ctx, name, RR_THRESHOLD_PASS, RR_THRESHOLD_UNCLEAR
    )
    override_note = _combine_notes(weight_note, t_note)

    if (
        ctx.entry_price is None
        or ctx.stop_loss_price is None
        or ctx.take_profit_price is None
    ):
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="entry/SL/TP missing in journal",
            override_applied=override_note,
        )

    risk = abs(ctx.entry_price - ctx.stop_loss_price)
    if risk == 0:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="entry == SL (risk = 0)",
            override_applied=override_note,
        )

    reward = abs(ctx.take_profit_price - ctx.entry_price)
    rr = reward / risk

    if rr >= threshold_pass:
        return CategoryResult(
            name=name,
            status="pass",
            score_contribution=max_points,
            max_points=max_points,
            threshold_used=f"planned_rr={rr:.2f} >= {threshold_pass}",
            override_applied=override_note,
        )
    if rr >= threshold_unclear:
        return CategoryResult(
            name=name,
            status="unclear",
            score_contribution=round(max_points * 0.5),
            max_points=max_points,
            threshold_used=f"planned_rr={rr:.2f} in [{threshold_unclear},{threshold_pass})",
            override_applied=override_note,
        )
    return CategoryResult(
        name=name,
        status="fail",
        score_contribution=0,
        max_points=max_points,
        threshold_used=f"planned_rr={rr:.2f} < {threshold_unclear}",
        override_applied=override_note,
    )


def evaluate_news(ctx: EvaluationContext) -> CategoryResult:
    """News/Macro (5 pts) — V1: always not_available (Tier-3 stubs only).

    Phase 31/33 will replace get_news_context + get_macro_context with real
    data; until then, this evaluator reports not_available so the Confidence
    Degradation Rule fires (CATEGORY_CAPABILITY_MAP[News] = HIGH/HIGH for
    both stub tools).
    """
    name = "News"
    max_points, weight_note = safe_resolve_weight(
        ctx.strategy_id, name, ctx, NEWS_MAX_POINTS
    )
    return CategoryResult(
        name=name,
        status="not_available",
        score_contribution=0,
        max_points=max_points,
        threshold_used="V1: Tier-3 stubs only — Phase 31/33 will populate",
        override_applied=weight_note,
    )


def evaluate_compression(ctx: EvaluationContext) -> CategoryResult:
    """Compression/Pause (10 pts) — L4 range_contraction_score in last 8 M5 bars.

    pass: max(score) >= 0.7
    unclear: in (0.4, 0.7)
    fail: <= 0.4
    not_available: M5 L4 absent or range_contraction_score missing in all bars.
    """
    name = "Compression"
    max_points, weight_note = safe_resolve_weight(
        ctx.strategy_id, name, ctx, COMPRESSION_MAX_POINTS
    )
    threshold_strong, threshold_weak, t_note = _resolve_override_thresholds(
        ctx, name, COMPRESSION_SCORE_PASS, COMPRESSION_SCORE_UNCLEAR
    )
    override_note = _combine_notes(weight_note, t_note)

    m5 = ctx.primitives_m5
    if m5 is None or m5.status == "not_available":
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="M5 primitives unavailable",
            override_applied=override_note,
        )

    layers = getattr(m5.data, "layers", []) or []
    layer4 = next((lb for lb in layers if getattr(lb, "layer", None) == 4), None)
    if layer4 is None or getattr(layer4, "count", 0) == 0:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="L4 absent",
            override_applied=override_note,
        )

    bars = getattr(layer4, "bars", []) or []
    recent = bars[-8:]
    scores = [
        b.get("range_contraction_score")
        for b in recent
        if b.get("range_contraction_score") is not None
    ]
    if not scores:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="range_contraction_score missing in L4 bars",
            override_applied=override_note,
        )
    peak = max(scores)

    if peak >= threshold_strong:
        return CategoryResult(
            name=name,
            status="pass",
            score_contribution=max_points,
            max_points=max_points,
            threshold_used=f"max range_contraction_score={peak:.2f} >= {threshold_strong}",
            override_applied=override_note,
        )
    if peak > threshold_weak:
        return CategoryResult(
            name=name,
            status="unclear",
            score_contribution=round(max_points * 0.5),
            max_points=max_points,
            threshold_used=f"max range_contraction_score={peak:.2f} in ({threshold_weak},{threshold_strong})",
            override_applied=override_note,
        )
    return CategoryResult(
        name=name,
        status="fail",
        score_contribution=0,
        max_points=max_points,
        threshold_used=f"max range_contraction_score={peak:.2f} <= {threshold_weak}",
        override_applied=override_note,
    )


def evaluate_liquidity(ctx: EvaluationContext) -> CategoryResult:
    """Liquidity (10 pts) — active FVG distance from entry in ATR units.

    pass: nearest active FVG midpoint within STRONG (1.0) ATR of entry
    unclear: within WEAK (1.5) ATR
    fail: outside WEAK
    not_available: liquidity_m15 envelope is not_available, no fvg_zones, or
    no entry_price.
    """
    name = "Liquidity"
    max_points, weight_note = safe_resolve_weight(
        ctx.strategy_id, name, ctx, LIQUIDITY_MAX_POINTS
    )
    threshold_strong, threshold_weak, t_note = _resolve_override_thresholds(
        ctx, name, LIQUIDITY_PROXIMITY_ATR_STRONG, LIQUIDITY_PROXIMITY_ATR_WEAK
    )
    override_note = _combine_notes(weight_note, t_note)

    liq = ctx.liquidity_m15
    if liq is None or liq.status == "not_available":
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="liquidity_m15 unavailable",
            override_applied=override_note,
        )

    fvg_zones = getattr(liq.data, "fvg_zones", None) or []
    if not fvg_zones:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="no fvg_zones in liquidity_m15",
            override_applied=override_note,
        )
    if ctx.entry_price is None:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="entry_price missing",
            override_applied=override_note,
        )

    # FVG zones are heterogeneous dicts (Phase 47.2.1 LiquidityData uses
    # ``list[dict[str, Any]]``). Use dict.get with a midpoint computed from
    # high/low when no explicit midpoint is provided.
    atr = _get_atr_from_m5(ctx) or 0.001
    distances: list[float] = []
    for z in fvg_zones:
        if not z.get("active", True):
            continue
        midpoint = z.get("midpoint")
        if midpoint is None:
            high = z.get("high")
            low = z.get("low")
            if high is not None and low is not None:
                midpoint = (high + low) / 2
        if midpoint is None:
            continue
        distances.append(abs(ctx.entry_price - midpoint) / atr)

    if not distances:
        return CategoryResult(
            name=name,
            status="not_available",
            score_contribution=0,
            max_points=max_points,
            threshold_used="no usable active FVG zones",
            override_applied=override_note,
        )
    nearest = min(distances)

    if nearest <= threshold_strong:
        return CategoryResult(
            name=name,
            status="pass",
            score_contribution=max_points,
            max_points=max_points,
            threshold_used=f"nearest FVG at {nearest:.2f} ATR <= {threshold_strong}",
            override_applied=override_note,
        )
    if nearest <= threshold_weak:
        return CategoryResult(
            name=name,
            status="unclear",
            score_contribution=round(max_points * 0.5),
            max_points=max_points,
            threshold_used=f"nearest FVG at {nearest:.2f} ATR in ({threshold_strong},{threshold_weak}]",
            override_applied=override_note,
        )
    return CategoryResult(
        name=name,
        status="fail",
        score_contribution=0,
        max_points=max_points,
        threshold_used=f"nearest FVG at {nearest:.2f} ATR > {threshold_weak}",
        override_applied=override_note,
    )


# === Evaluators 6-9: Plan 04 Task 2 ships these ===
# evaluate_htf, evaluate_location, evaluate_structure, evaluate_pullback +
# EVALUATOR_DISPATCH live below — appended in Task 2.
