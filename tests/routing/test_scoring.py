"""
Scoring function tests — covers cost/latency/quality score normalization.

All tests xfail until Plan 02 implements real scoring formulas.
The placeholder return value (0.5) means tests would pass numerically,
but the semantic assertions (e.g. local_is_one) require real implementation.

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_scoring.py -x -q
"""
import pytest
from core.routing import scoring


def test_cost_score_local_is_one():
    """Local tier model (output_cost_per_1k=0.0) scores 1.0 (perfect cost score)."""
    pytest.xfail("Plan 02: cost_score formula pending")


def test_cost_score_most_expensive_is_zero():
    """Most expensive model in the pool scores 0.0 (worst cost score)."""
    pytest.xfail("Plan 02: cost_score formula pending")


def test_latency_score_uses_table():
    """Latency score derived from static latency_table; unknown model defaults to 5000ms."""
    pytest.xfail("Plan 02: latency_score pending")


def test_quality_score_default_mid():
    """Unknown model quality_score defaults to 0.5 (neutral quality assumption)."""
    pytest.xfail("Plan 02: quality_score pending")


def test_composite_score_uses_weights():
    """Composite score = quality_weight*quality + cost_weight*cost + latency_weight*latency."""
    pytest.xfail("Plan 02: composite formula pending")
