"""Phase 89 Wave 2 — counterfactual_engine core module.

Public API:
    query_analogues(indicator, hypothetical_surprise, k, current_regime)
        — query Phase 87 Neo4j graph for historical analogues
    forecast_market_impact(indicator, hypothetical, analogues, asset_keys, windows)
        — run event-study via Phase 86 (or Phase 90 Layer 4 when available)

Decision 2: n=5 hard floor — engine refuses if fewer than k_analogues_minimum analogues.
Decision 12: wraps Phase 90 /forecast/market-impact when PHASE_90_FORECAST_URL set + healthy.
Pitfall 5: fallback to Phase 86 event-study when Phase 90 absent — NEVER silent error.
"""
from __future__ import annotations

from core.counterfactual.output_contract import (
    CounterfactualOutput,
    CounterfactualResponse,
    ExpectedMove,
    InsufficientAnaloguesResponse,
    BlockingContradictionRefusal,
)
from core.counterfactual.analogue_retrieval import query_analogues
from core.counterfactual.forecast_client import forecast_market_impact, ForecastUnavailable

__all__ = [
    "CounterfactualOutput",
    "CounterfactualResponse",
    "ExpectedMove",
    "InsufficientAnaloguesResponse",
    "BlockingContradictionRefusal",
    "ForecastUnavailable",
    "query_analogues",
    "forecast_market_impact",
]
