"""Phase 88.1 Plan 08 — indicator_enrichment_agent package.

VM107 write-time Pydantic gate agent for AI enrichment of economic indicators.
Layer 2 of the 3-layer AI Description architecture:
  Layer 1 — Curator YAML (permanent source of truth, AI never writes here)
  Layer 2 — This agent: generates IndicatorEnrichment and validates via Pydantic
  Layer 3 — VM100 frontend merges curator + AI enrichment at render time

Invocation contract:
    POST /api/v1/agents/indicator_enrichment/invoke
    Body: {indicator_id: str, curator_layer?: dict}
    Response: IndicatorEnrichment.model_dump() | error envelope

Retry pattern (Phase 38): validates output via IndicatorEnrichment.model_validate()
and retries once on ValidationError. Second failure raises to caller.
"""
from agents.indicator_enrichment_agent.agent import IndicatorEnrichmentAgent

__all__ = ['IndicatorEnrichmentAgent']
