"""Phase 86 Plan 07 — macro_historical_analyst agent package.

Event-driven single-emit-terminate agent for historical macro event study narration.

Architecture decisions (per CONTEXT.md):
- D5: event-driven, NOT scheduled, NOT background loop
- D7: no Brain B5/B6/B9/B13 absorbed; pure factual narration
- ARCHITECTURE §6: narrative MUST cite sample_size N AND period verbatim

Invocation contract:
    POST /api/v1/agents/macro_historical_analyst/invoke
    Body: {envelope, result, indicator_name, asset_names}
    Response: {envelope: {tool_id, confidence, provenance, latency_ms}, result: {narrative}, error}

Plan 86-08 will wire the VM100 -> VM107 dispatch on macro_event_study_run window event.
Plan 86-09 will add the capability registry YAML.
"""
from agents.macro_historical_analyst.agent import MacroHistoricalAnalyst

__all__ = ["MacroHistoricalAnalyst"]
