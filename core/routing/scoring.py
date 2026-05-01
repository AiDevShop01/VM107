"""
Score normalization functions for model candidate ranking.

Pure functions — no side effects, no I/O, no external dependencies.
Used by ModelRouter._select_candidates() to rank candidates before
brain-mode and latency filters are applied.

Score semantics (all scores: 0.0 = worst, 1.0 = best):
    cost_score:    1.0 = free (local), 0.0 = most expensive in pool
    latency_score: 1.0 = fastest, 0.0 = slowest in pool
    quality_score: 1.0 = highest quality (manually curated from arena rankings)

Composite formula (from CONTEXT.md locked mode_weights):
    score = quality_weight * quality_score
           + cost_weight * cost_score
           + latency_weight * latency_score

Implementation plan: Plan 02 replaces placeholder return values with real formulas.
"""
from __future__ import annotations


def compute_cost_score(model_id: str, all_models: list[dict]) -> float:
    """
    Compute normalized cost score for a model.

    Higher score = cheaper. 1.0 = free (local tier). 0.0 = most expensive in pool.
    Formula: 1.0 - (model_cost / max_cost_in_pool). Local ($0.00) = 1.0.

    Args:
        model_id: Model identifier to score
        all_models: List of model dicts with keys: model_id, output_cost_per_1k

    Returns:
        Cost score in [0.0, 1.0]. Returns 0.5 until Plan 02 implements real formula.

    Raises:
        NotImplementedError: Plan 02 placeholder — returns 0.5 for now.
    """
    # Phase 43 Plan 02: implement real formula
    # Formula: 1.0 - (model_cost / max_cost) where max_cost = max(output_cost_per_1k)
    # Local tier (output_cost_per_1k == 0.0) -> return 1.0
    return 0.5  # placeholder until Plan 02


def compute_latency_score(model_id: str, latency_table: dict) -> float:
    """
    Compute normalized latency score for a model.

    Higher score = faster. Uses static latency table (no LiteLLM source —
    latency_ms values come from model_routing.yaml model catalog).
    Formula: 1.0 - (latency_ms / max_latency_in_table).

    Args:
        model_id: Model identifier to score
        latency_table: Dict of {model_id: latency_ms}. Unknown models default to 5000ms.

    Returns:
        Latency score in [0.0, 1.0]. Returns 0.5 until Plan 02 implements real formula.
    """
    # Phase 43 Plan 02: implement real formula
    # Formula: 1.0 - (latency_ms / max_latency) where latency_ms from latency_table
    # Unknown model_id -> default to 5000ms
    return 0.5  # placeholder until Plan 02


def compute_quality_score(model_id: str, quality_table: dict) -> float:
    """
    Compute quality score for a model.

    Quality scores are manually curated from LMSys Chatbot Arena Elo rankings and
    stored in model_routing.yaml model catalog (quality_score field per model).
    No automated source exists — this table is manually maintained.

    Phase 44+ will replace with empirical performance tracking.

    Args:
        model_id: Model identifier to score
        quality_table: Dict of {model_id: quality_score (0.0-1.0)}.
                       Unknown models default to 0.5 (neutral).

    Returns:
        Quality score in [0.0, 1.0]. Returns 0.5 until Plan 02 implements real lookup.
    """
    # Phase 43 Plan 02: implement real lookup from quality_table
    # Unknown model_id -> return 0.5 (neutral quality assumption)
    return 0.5  # placeholder until Plan 02


def compute_composite(
    quality_score: float,
    cost_score: float,
    latency_score: float,
    weights: dict,
) -> float:
    """
    Compute composite model score using mode-specific weights.

    Formula (from CONTEXT.md locked spec):
        score = weights["quality"] * quality_score
               + weights["cost"] * cost_score
               + weights["latency"] * latency_score

    Weights must sum to 1.0 (enforced by model_routing.yaml validator).

    Args:
        quality_score: Normalized quality score [0.0, 1.0]
        cost_score: Normalized cost score [0.0, 1.0]
        latency_score: Normalized latency score [0.0, 1.0]
        weights: Dict with keys: quality, cost, latency (must sum to 1.0)

    Returns:
        Composite score in [0.0, 1.0]. Returns 0.5 until Plan 02 implements formula.
    """
    # Phase 43 Plan 02: implement real formula
    # score = w["quality"] * quality + w["cost"] * cost + w["latency"] * latency
    return 0.5  # placeholder until Plan 02
