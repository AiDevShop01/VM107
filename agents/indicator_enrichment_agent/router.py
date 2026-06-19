"""Phase 88.1 Plan 08 — indicator_enrichment_agent router module.

Lightweight re-export documenting the invocation contract.
The HTTP route is registered via the VM107 auto-discovery mechanism at:
    api/v1/agents/indicator_enrichment/invoke

Invocation contract:
    POST /api/v1/agents/indicator_enrichment/invoke
    Headers: X-API-KEY: <vm107 service key>
    Body: {
        "indicator_id": "CPIAUCSL",
        "curator_layer": {
            "indicator_id": "CPIAUCSL",
            "name": "Consumer Price Index for All Urban Consumers",
            "category": "inflation",
            "frequency": "monthly",
            "country": "US",
            "importance": "critical",
            "short_description": "...",
            "why_it_matters": "...",
            "affected_assets": ["DEXUSEU", "DGS10", "SP500"]
        }
    }
    Response 200: IndicatorEnrichment.model_dump() — 9-field object:
        {
            "indicator_id": "CPIAUCSL",
            "current_narrative": "...",
            "trading_implications": "...",
            "recent_changes": "...",
            "confidence": 0.85,
            "generated_at": "2026-06-19T10:00:00Z",
            "version": 1,
            "model": "claude-...",
            "prompt_version": "88.1.0"
        }
    Response 422: Validation error (both attempts failed Pydantic gate)
    Response 500: System error

Fallback hierarchy (caller's responsibility — agent raises on failure):
    AI success → return IndicatorEnrichment.model_dump()
    AI fail (ValidationError/ValueError) → caller falls back to curator Layer 1
    Curator missing → caller renders Insufficient Metadata state
    System error → caller renders Error state

Plan 09 will wire the regeneration triggers (new_release, regime_change,
relationship_drift, seven_day_elapsed, manual_refresh).
"""
from agents.indicator_enrichment_agent.agent import IndicatorEnrichmentAgent

__all__ = ['IndicatorEnrichmentAgent']
