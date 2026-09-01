"""Phase 173 Plan 04 (D-08) — LiquidityScore typed-contract tests.

Proves the promotion of ``macro_liquidity_monitor`` from a bare ``float | None``
return to a typed Pydantic ``LiquidityScore`` boundary while PRESERVING the
house honest-null semantics: an empty / incomplete substrate yields
``LiquidityScore(score=None, degraded=True, tier=None)`` — NEVER coerced to 0.

RED until the contract + wrapper (Task 2) exist. The tier-threshold mapping is
asserted against the single-source constants in ``agent.py`` so the test cannot
drift from the emit logic.
"""
from __future__ import annotations

import pytest

from agents.macro_liquidity_monitor.agent import (
    _BLOCKING_THRESHOLD,
    _WARNING_THRESHOLD,
    score_liquidity,
)
from agents.macro_liquidity_monitor.contract import LiquidityScore


@pytest.mark.quick
def test_empty_substrate_is_honest_null_not_zero() -> None:
    """Empty substrate → score=None, degraded=True, tier=None (never 0)."""
    result = score_liquidity({})

    assert isinstance(result, LiquidityScore)
    assert result.score is None
    assert result.degraded is True
    assert result.tier is None
    # Honest-null hard invariant: None must NOT be coerced to a neutral 0.
    assert result.score != 0
    assert result.producer_agent_id == "vm107.macro_liquidity_monitor"


@pytest.mark.quick
def test_no_contributing_keys_is_honest_null() -> None:
    """A substrate with no recognised signal keys still yields honest-null."""
    result = score_liquidity({"unrelated_key": 123})

    assert result.score is None
    assert result.degraded is True
    assert result.tier is None
    assert result.substrate_keys_present == []


def test_tier_blocking_below_blocking_threshold() -> None:
    """Score < _BLOCKING_THRESHOLD (20) → tier='blocking', degraded=False."""
    # credit_spreads_widened(-25) + funding_stress_index=1.0(-50) + dxy=3(-25) → 0
    result = score_liquidity(
        {
            "credit_spreads_widened": True,
            "funding_stress_index": 1.0,
            "dxy_spike_24h": 3.0,
        }
    )

    assert result.score is not None
    assert result.score < _BLOCKING_THRESHOLD
    assert result.tier == "blocking"
    assert result.degraded is False


def test_tier_warning_in_warning_band() -> None:
    """_BLOCKING_THRESHOLD <= score < _WARNING_THRESHOLD (30) → tier='warning'."""
    # funding_stress_index=1.0(-50) + dxy=3(-25) → 25 ∈ [20, 30)
    result = score_liquidity({"funding_stress_index": 1.0, "dxy_spike_24h": 3.0})

    assert result.score is not None
    assert _BLOCKING_THRESHOLD <= result.score < _WARNING_THRESHOLD
    assert result.tier == "warning"
    assert result.degraded is False


def test_tier_normal_at_or_above_warning_threshold() -> None:
    """Score >= _WARNING_THRESHOLD (30) → tier='normal'."""
    # credit_spreads_widened=False contributes but subtracts nothing → 100
    result = score_liquidity({"credit_spreads_widened": False})

    assert result.score is not None
    assert result.score >= _WARNING_THRESHOLD
    assert result.tier == "normal"
    assert result.degraded is False


def test_substrate_keys_present_is_provenance() -> None:
    """substrate_keys_present reflects the contributing substrate keys."""
    result = score_liquidity(
        {"credit_spreads_widened": True, "funding_stress_index": 0.5}
    )

    assert set(result.substrate_keys_present) == {
        "credit_spreads_widened",
        "funding_stress_index",
    }
    assert result.producer_agent_id == "vm107.macro_liquidity_monitor"
