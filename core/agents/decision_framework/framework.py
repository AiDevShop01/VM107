"""Phase 47.3 — Framework orchestrator.

Stateless. One instance per process is fine. ``Framework()`` instantiation
runs boot-time invariant checks (OQ-1 + OQ-7) — fails fast on configuration
violations.

Boot-time invariants:
  1. ``sum(CATEGORY_MAX_POINTS.values()) == 100`` (OQ-1).
  2. Every ``hard_rejects[].name`` in every strategy YAML at
     ``agents/agent0/strategies/*.yaml`` has a registered Python predicate
     (OQ-7 / CF-5). Plan 05 ships the predicates; until then strategy YAMLs
     with hard_rejects will fail this check (intentional — Plans 03 and 05
     ship in the same wave).

Run-time flow:
  1. Run 9 evaluators in canonical CATEGORY_ORDER (Plan 04 fills the bodies).
  2. Aggregate score / max_score (LOCK 4: not_available contributes 0;
     max_score stays at the original allocation).
  3. Compute confidence adjustments (Confidence Degradation Rule, CF-1).
  4. Derive recommendation band from score.
  5. Apply hard_reject veto: if any predicate fires, recommendation → "avoid"
     (score and max_score stay visible — LOCK 5).
  6. CF-5: if ctx.strategy is None, populate ``no_strategy_warning`` so the
     gap is explicit in the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml

from .bands import derive_recommendation_band
from .confidence import compute_confidence_adjustments
from .context import EvaluationContext
from .hard_rejects import detect_hard_rejects, is_hard_reject_registered
from .thresholds import BASE_CONFIDENCE, CATEGORY_MAX_POINTS

CATEGORY_ORDER: list[str] = [
    "HTF",
    "Location",
    "Liquidity",
    "Structure",
    "Momentum",
    "Compression",
    "Pullback",
    "RR",
    "News",
]
FRAMEWORK_VERSION = 1

# VM107/agents/agent0/strategies/*.yaml — resolved relative to this module.
# decision_framework/framework.py → decision_framework/ → agents/ → core/
# → VM107/ root → agents/agent0/strategies
STRATEGIES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "agents"
    / "agent0"
    / "strategies"
)


@dataclass(frozen=True)
class PythonEngineResult:
    """Aggregated output of ``Framework.run(ctx)``.

    All Python-owned fields. The LLM in Mode B reads this dataclass and
    produces narrative fields (reasoning_summary, risks, invalidations,
    next_action) on top — it cannot modify the values here.
    """

    score: int
    max_score: int
    recommendation: Literal["enter", "wait", "avoid", "needs_more_confirmation"]
    confidence_pct: int  # clamped to [0, 100]
    partial_context: bool
    category_results: list  # list[CategoryResult]
    confidence_adjustments: list  # list[ConfidenceAdjustment]
    hard_reject_reasons: list[str] = field(default_factory=list)
    no_strategy_warning: Optional[str] = None  # CF-5
    framework_version: int = FRAMEWORK_VERSION


def _validate_boot_invariants() -> None:
    """OQ-1: assert ``sum(CATEGORY_MAX_POINTS.values()) == 100``.
    OQ-7 / CF-5: every YAML hard_reject name has a registered Python predicate.

    Called from ``Framework.__init__``. Raises RuntimeError on violation.
    """
    # OQ-1 — module-load assert in thresholds.py already enforces this; restate
    # here so test_max_score_invariant_assertion_at_boot has a clear hook.
    total = sum(CATEGORY_MAX_POINTS.values())
    if total != 100:
        raise RuntimeError(
            f"Phase 47.3 invariant violated: CATEGORY_MAX_POINTS sums to "
            f"{total}, not 100."
        )

    # OQ-7 / CF-5 — strategy YAML hard_rejects names must each have a
    # registered predicate. Plan 05 ships the predicates; until then, any
    # strategy YAML with hard_rejects fails this check (deliberate).
    if not STRATEGIES_DIR.exists():
        # No strategies directory — skip (test environment, etc.).
        return
    missing: list[str] = []
    for yaml_path in sorted(STRATEGIES_DIR.glob("*.yaml")):
        with yaml_path.open() as f:
            data = yaml.safe_load(f) or {}
        strategy_id = data.get("id") or yaml_path.stem
        for hr in data.get("hard_rejects", []) or []:
            name = hr.get("name") if isinstance(hr, dict) else hr
            if not name:
                continue
            if not is_hard_reject_registered(strategy_id, name):
                missing.append(f"{strategy_id}.{name}")
    if missing:
        raise RuntimeError(
            f"Phase 47.3 invariant violated: hard_reject predicates missing "
            f"for: {', '.join(missing)}. Plan 05 must register these in "
            f"core/agents/decision_framework/strategies/<id>.py."
        )


class Framework:
    """V1 decision framework. Stateless; one instance per process is fine."""

    def __init__(self):
        # Trigger import side-effect of strategies package so all overrides
        # + hard-reject predicates are registered before invariant check.
        from . import strategies  # noqa: F401

        _validate_boot_invariants()

    def run(self, ctx: EvaluationContext) -> PythonEngineResult:
        """Execute the 9-category framework on ``ctx`` and return a result.

        Plan 04 ships ``category_evaluators.EVALUATOR_DISPATCH`` — the
        9-stub-evaluator dispatch table. This method imports lazily so the
        framework module can be imported even before Plan 04 ships.
        """
        # Late import — Plan 04 ships category_evaluators.
        from .category_evaluators import EVALUATOR_DISPATCH  # noqa: F401

        # Step 1 — run 9 evaluators in canonical order.
        results = [EVALUATOR_DISPATCH[name](ctx) for name in CATEGORY_ORDER]

        # Step 2 — aggregate score + max_score.
        # LOCK 4: not_available contributes 0; max_score stays at original
        # allocation (the gap shows up as a confidence dock, not a score
        # rebalance).
        score = sum(r.score_contribution for r in results)
        max_score = sum(r.max_points for r in results)

        # Step 3 — confidence degradation.
        adjustments = compute_confidence_adjustments(ctx, results)
        confidence_pct = max(
            0, min(100, BASE_CONFIDENCE + sum(a.impact for a in adjustments))
        )
        partial_context = any(a.impact_tier == "HIGH" for a in adjustments)

        # Step 4 — recommendation band (pre-veto).
        recommendation = derive_recommendation_band(score)

        # Step 5 — hard reject veto (post-band; score+band stay visible).
        hard_reject_reasons: list[str] = []
        no_strategy_warning: Optional[str] = None
        if ctx.strategy and ctx.strategy.hard_rejects:
            hard_reject_reasons = detect_hard_rejects(ctx, results)
            if hard_reject_reasons:
                recommendation = "avoid"
        elif ctx.strategy_id is None:
            # CF-5 — no strategy attached; signal the gap explicitly.
            no_strategy_warning = (
                "no strategy attached — hard rejects not evaluated"
            )

        return PythonEngineResult(
            score=score,
            max_score=max_score,
            recommendation=recommendation,
            confidence_pct=confidence_pct,
            partial_context=partial_context,
            category_results=results,
            confidence_adjustments=adjustments,
            hard_reject_reasons=hard_reject_reasons,
            no_strategy_warning=no_strategy_warning,
        )
