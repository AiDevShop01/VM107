"""
Pure score normalization functions for model candidate ranking.

All functions are pure — no side effects, no I/O, no external dependencies.
Used by ModelRouter._select_candidates() to rank candidates before brain-mode
and latency filters are applied.

Score semantics (all scores: 0.0 = worst, 1.0 = best):
    cost_score:    1.0 = free (local), 0.0 = most expensive in pool
    latency_score: 1.0 = fastest, 0.0 = slowest in pool
    quality_score: 1.0 = highest quality (LMSys-Elo seeded; manually curated until Phase 44+)

Composite formula (from CONTEXT.md locked mode_weights):
    score = quality_weight * quality_score
           + cost_weight * cost_score
           + latency_weight * latency_score

Fail-safe defaults for unknown models:
    cost_score:    0.0 (don't route to unknown models — worst cost score)
    latency_score: 0.0 (don't route to unknown models — worst latency score)
    quality_score: 0.5 (neutral quality assumption per RESEARCH.md)

Inputs come from model_routing.yaml -> models catalog (cost/latency/quality fields).
"""
from __future__ import annotations

from typing import Mapping


def compute_cost_score(model_id: str, all_models: Mapping[str, dict]) -> float:
    """
    Compute normalized cost score for a model.

    Higher score = cheaper. 1.0 = free (local tier). 0.0 = most expensive in pool.
    Formula: 1.0 - (model_cost / max_cost_in_pool). Local ($0.00) = 1.0 exactly.

    Unknown models return 0.0 (fail-safe: don't route to unknown models).

    Args:
        model_id: Model identifier to score.
        all_models: Mapping of model_id -> model dict with cost_per_1k_output_usd field.

    Returns:
        Cost score in [0.0, 1.0].
    """
    meta = all_models.get(model_id)
    if meta is None:
        return 0.0  # unknown model = worst cost score

    c = meta.get("cost_per_1k_output_usd", 0.0)
    if c <= 0.0:
        return 1.0  # free (local) model

    # Find max cost among all paid models in the catalog
    paid_costs = [
        m["cost_per_1k_output_usd"]
        for m in all_models.values()
        if m.get("cost_per_1k_output_usd", 0.0) > 0.0
    ]
    max_cost = max(paid_costs) if paid_costs else 1.0

    return max(0.0, 1.0 - (c / max_cost))


def compute_latency_score(model_id: str, all_models: Mapping[str, dict]) -> float:
    """
    Compute normalized latency score for a model.

    Higher score = faster. Uses static latency_ms from model_routing.yaml catalog.
    Formula: 1.0 - (latency_ms / max_latency_in_catalog).

    Unknown models return 0.0 (fail-safe: don't route to unknown models).

    Args:
        model_id: Model identifier to score.
        all_models: Mapping of model_id -> model dict with latency_ms field.

    Returns:
        Latency score in [0.0, 1.0].
    """
    meta = all_models.get(model_id)
    if meta is None:
        return 0.0  # unknown model = worst latency score

    latencies = [m.get("latency_ms", 5000) for m in all_models.values()]
    max_latency = max(latencies) if latencies else 10000

    lat = meta.get("latency_ms", 5000)
    return max(0.0, 1.0 - (lat / max_latency))


def compute_quality_score(model_id: str, all_models: Mapping[str, dict]) -> float:
    """
    Compute quality score for a model.

    Quality scores are manually curated from LMSys Chatbot Arena Elo rankings and
    stored in model_routing.yaml model catalog (quality_score field per model).
    No automated source exists — this table is manually maintained.

    Phase 44+ will replace with empirical performance tracking.

    Unknown models return 0.5 (neutral quality assumption per RESEARCH.md).

    Args:
        model_id: Model identifier to score.
        all_models: Mapping of model_id -> model dict with quality_score field.

    Returns:
        Quality score in [0.0, 1.0]. Defaults to 0.5 for unknown models.
    """
    meta = all_models.get(model_id)
    if meta is None:
        return 0.5  # unknown model = mid-quality neutral assumption

    return float(meta.get("quality_score", 0.5))


def compute_composite(
    quality: float,
    cost: float,
    latency: float,
    weights: dict,
) -> float:
    """
    Compute composite model score using mode-specific weights.

    Formula (from CONTEXT.md locked spec):
        score = weights["quality"] * quality
               + weights["cost"] * cost
               + weights["latency"] * latency

    Weights must sum to 1.0 (enforced by AffinityMap._validate_mode_weights at load time).

    Args:
        quality: Normalized quality score [0.0, 1.0]
        cost: Normalized cost score [0.0, 1.0]
        latency: Normalized latency score [0.0, 1.0]
        weights: Dict with keys: quality, cost, latency (must sum to 1.0)

    Returns:
        Composite score in [0.0, 1.0].
    """
    return (
        weights["quality"] * quality
        + weights["cost"] * cost
        + weights["latency"] * latency
    )
