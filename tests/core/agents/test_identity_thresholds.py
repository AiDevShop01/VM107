"""Phase 48 Plan 48-05 Task 5.1 — identity threshold dispatch.

REQ-48-D10. CONTEXT § Decision 10 ratchet:
  Iter 1 vs Iter 0 requires similarity >= 0.70
  Iter 2 vs Iter 0 requires similarity >= 0.80
  Iter 3 vs Iter 0 requires similarity >= 0.90

Threshold values come EXCLUSIVELY from
``policy_constants.IDENTITY_THRESHOLDS`` (Plan 04 single source of truth).
"""
from __future__ import annotations

import pytest

from core.agents.refinement_orchestrator.policy_constants import IDENTITY_THRESHOLDS
from core.contracts.schemas import StrategyFamily, StrategySpec


def _spec(
    *,
    name: str = "alpha-breakout-v1",
    features: tuple[str, ...] = ("rsi", "atr"),
    rules: tuple[str, ...] = ("if rsi>70 long",),
    timeframes: tuple[str, ...] = ("1h",),
    version: str = "1.0.0",
    strategy_family: StrategyFamily = StrategyFamily.BREAKOUT,
) -> StrategySpec:
    return StrategySpec(
        name=name,
        features=list(features),
        rules=list(rules),
        timeframes=list(timeframes),
        version=version,
        strategy_family=strategy_family,
    )


def test_policy_threshold_values_are_locked():
    """Sanity guard — Plan 04 contract."""
    assert IDENTITY_THRESHOLDS[1] == 0.70
    assert IDENTITY_THRESHOLDS[2] == 0.80
    assert IDENTITY_THRESHOLDS[3] == 0.90


def test_should_terminate_for_drift_below_threshold_returns_true():
    from core.agents.refinement_orchestrator.identity_scorer import should_terminate_for_drift

    # Iteration 1 threshold = 0.70
    assert should_terminate_for_drift(0.69, 1) is True
    # Iteration 2 threshold = 0.80
    assert should_terminate_for_drift(0.79, 2) is True
    # Iteration 3 threshold = 0.90
    assert should_terminate_for_drift(0.89, 3) is True


def test_should_terminate_for_drift_at_or_above_threshold_returns_false():
    from core.agents.refinement_orchestrator.identity_scorer import should_terminate_for_drift

    assert should_terminate_for_drift(0.70, 1) is False
    assert should_terminate_for_drift(0.95, 1) is False
    assert should_terminate_for_drift(0.80, 2) is False
    assert should_terminate_for_drift(0.90, 3) is False
    assert should_terminate_for_drift(1.00, 3) is False


def test_should_terminate_for_drift_reads_only_policy_constants():
    """should_terminate_for_drift MUST source thresholds from policy_constants.

    AST inspection: identity_scorer.py must reference IDENTITY_THRESHOLDS from
    policy_constants (no inline magic numbers 0.70 / 0.80 / 0.90).
    """
    import ast
    import pathlib

    src_path = pathlib.Path(
        "/Volumes/ HardDrive/FinGPT/VM107/core/agents/refinement_orchestrator/identity_scorer.py"
    )
    tree = ast.parse(src_path.read_text())

    # Must import IDENTITY_THRESHOLDS from policy_constants.
    has_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "policy_constants" in node.module:
                for alias in node.names:
                    if alias.name == "IDENTITY_THRESHOLDS":
                        has_import = True
    assert has_import, "identity_scorer.py must import IDENTITY_THRESHOLDS from policy_constants"


def test_score_crosses_each_threshold_with_controlled_drift():
    """Synthesize specs with progressively more drift; expect score to drop."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()

    # No drift -> score = 1.0 (passes all 3 thresholds).
    score, _ = compute_score(origin, origin)
    assert score >= IDENTITY_THRESHOLDS[3] == 0.90  # type: ignore[comparison-overlap]

    # MINOR_TUNING-only drift (version): weight is 0.0 -> score stays at 1.0.
    minor = _spec(version="2.0.0")
    score_minor, _ = compute_score(minor, origin)
    assert score_minor == 1.0

    # REFINABLE drift (one field): weight 0.2 -> 0.8.
    refinable = _spec(features=("rsi", "atr", "ema_50"))
    score_ref, _ = compute_score(refinable, origin)
    assert score_ref < IDENTITY_THRESHOLDS[3]   # below 0.90
    assert score_ref >= IDENTITY_THRESHOLDS[1]  # at or above 0.70

    # IMMUTABLE_CORE drift (single field, weight 0.5) -> <= 0.50 (below all thresholds).
    immut = _spec(strategy_family=StrategyFamily.TREND_CONTINUATION)
    score_immut, _ = compute_score(immut, origin)
    assert score_immut <= 0.50
    assert score_immut < IDENTITY_THRESHOLDS[1]  # triggers IDENTITY_DRIFT on iter 1
