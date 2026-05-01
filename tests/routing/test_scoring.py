"""
Scoring function tests — covers cost/latency/quality score normalization.

All tests assert real behavior now that Plan 02 implements scoring formulas.
Formula specs from CONTEXT.md (locked):
    cost_score:    1.0 = free (local), 0.0 = most expensive in pool
    latency_score: 1.0 - latency_ms/max_latency (higher = faster)
    quality_score: static from catalog; unknown model returns 0.5
    composite:     weighted sum using mode_weights from YAML

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_scoring.py -x -q
"""
import pytest
import yaml
from pathlib import Path
from core.routing import scoring

YAML_PATH = Path(__file__).parents[2] / "conf" / "model_routing.yaml"


def _models():
    """Load models catalog from model_routing.yaml."""
    return yaml.safe_load(YAML_PATH.read_text())["models"]


def test_cost_score_local_is_one():
    """Local tier model (cost=0.0) scores 1.0 (perfect cost score)."""
    assert scoring.compute_cost_score("ollama/llama3.2", _models()) == 1.0


def test_cost_score_most_expensive_is_zero():
    """Most expensive model in the pool (claude-4-opus at $0.075) scores 0.0."""
    assert scoring.compute_cost_score("anthropic/claude-4-opus-20250514", _models()) == 0.0


def test_cost_score_unknown_model_is_zero():
    """Unknown model returns 0.0 (fail-safe: don't route to unknown models)."""
    assert scoring.compute_cost_score("unknown/model", _models()) == 0.0


def test_cost_score_mid_range():
    """Mid-range model scores between 0.0 and 1.0."""
    score = scoring.compute_cost_score("openai/gpt-4o", _models())
    assert 0.0 < score < 1.0


def test_latency_score_uses_table():
    """Latency score derived from static catalog; lower latency = higher score."""
    m = _models()
    max_lat = max(v["latency_ms"] for v in m.values())
    expected = 1.0 - (m["openai/gpt-4o"]["latency_ms"] / max_lat)
    assert abs(scoring.compute_latency_score("openai/gpt-4o", m) - expected) < 1e-9


def test_latency_score_fastest_is_highest():
    """The model with the lowest latency_ms should have the highest latency_score."""
    m = _models()
    # ollama/llama3.2 has 300ms (lowest), should score highest
    score_fast = scoring.compute_latency_score("ollama/llama3.2", m)
    score_slow = scoring.compute_latency_score("anthropic/claude-4-opus-20250514", m)
    assert score_fast > score_slow


def test_latency_score_unknown_model_is_zero():
    """Unknown model latency score is 0.0 (fail-safe)."""
    assert scoring.compute_latency_score("unknown/model", _models()) == 0.0


def test_quality_score_default_mid():
    """Unknown model quality_score defaults to 0.5 (neutral quality assumption)."""
    assert scoring.compute_quality_score("unknown/model", {}) == 0.5


def test_quality_score_from_catalog():
    """Quality score reads directly from catalog field."""
    m = _models()
    assert scoring.compute_quality_score("anthropic/claude-4-sonnet-20250514", m) == 0.92


def test_quality_score_opus_is_highest():
    """claude-4-opus has quality_score=0.95 (highest in catalog)."""
    m = _models()
    assert scoring.compute_quality_score("anthropic/claude-4-opus-20250514", m) == 0.95


def test_composite_score_uses_weights():
    """Composite = quality_w*quality + cost_w*cost + latency_w*latency."""
    weights = {"quality": 0.6, "cost": 0.25, "latency": 0.15}
    result = scoring.compute_composite(0.8, 0.6, 0.4, weights)
    expected = 0.8 * 0.6 + 0.6 * 0.25 + 0.4 * 0.15
    assert abs(result - expected) < 1e-9


def test_composite_all_ones_is_one():
    """Composite of all 1.0 scores with summing-to-1 weights is 1.0."""
    weights = {"quality": 0.6, "cost": 0.25, "latency": 0.15}
    result = scoring.compute_composite(1.0, 1.0, 1.0, weights)
    assert abs(result - 1.0) < 1e-9


def test_composite_all_zeros_is_zero():
    """Composite of all 0.0 scores is 0.0."""
    weights = {"quality": 0.4, "cost": 0.4, "latency": 0.2}
    result = scoring.compute_composite(0.0, 0.0, 0.0, weights)
    assert result == 0.0
