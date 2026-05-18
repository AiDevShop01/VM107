"""Phase 48 Plan 48-05 Task 5.1 — identity_scorer determinism.

REQ-48-D10. Pure structured-diff Python score over StrategySpec fields,
NEVER embeddings/semantic similarity. Same inputs -> same output across
100 calls (no module-level mutable state, no randomness, no I/O).
"""
from __future__ import annotations

import pytest

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
    """Helper builder — frozen dataclass requires every field."""
    return StrategySpec(
        name=name,
        features=list(features),
        rules=list(rules),
        timeframes=list(timeframes),
        version=version,
        strategy_family=strategy_family,
    )


def test_compute_score_identity_returns_perfect_score():
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec = _spec()
    score, diff = compute_score(spec, spec)

    assert isinstance(score, float)
    assert score == 1.0
    assert isinstance(diff, list)
    assert diff == []


def test_compute_score_is_deterministic_100x():
    """Same input pair across 100 calls produces identical (score, diff)."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec_origin = _spec()
    spec_new = _spec(features=("rsi", "atr", "macd"), version="1.0.1")

    first_score, first_diff = compute_score(spec_new, spec_origin)
    for _ in range(99):
        score, diff = compute_score(spec_new, spec_origin)
        assert score == first_score
        assert diff == first_diff


def test_compute_score_returns_tuple_float_list():
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    result = compute_score(_spec(), _spec(version="1.0.2"))

    assert isinstance(result, tuple)
    assert len(result) == 2
    score, diff = result
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert isinstance(diff, list)


def test_score_is_clamped_to_unit_interval():
    """Even with every field divergent, score must NOT go below 0.0."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec_a = _spec(strategy_family=StrategyFamily.BREAKOUT)
    spec_b = _spec(
        name="entirely-different",
        features=("vwap", "tick_volume"),
        rules=("if vwap_cross long",),
        timeframes=("5m",),
        version="9.9.9",
        strategy_family=StrategyFamily.MEAN_REVERSION,
    )

    score, _ = compute_score(spec_b, spec_a)
    assert 0.0 <= score <= 1.0


def test_diff_breakdown_lists_per_field_entries():
    """Each diff entry must include field, severity, was, now, weight."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec_a = _spec()
    spec_b = _spec(features=("rsi", "atr", "ema_20"))

    _, diff = compute_score(spec_b, spec_a)
    assert len(diff) >= 1
    entry = diff[0]
    for required_key in ("field", "severity", "was", "now", "weight"):
        assert required_key in entry, f"missing {required_key!r} in {entry!r}"
    assert entry["severity"] in {"HIGH", "MEDIUM", "LOW"}
