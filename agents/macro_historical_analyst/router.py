"""Phase 86 Plan 07 — macro_historical_analyst router module.

This module is a lightweight re-export for documentation purposes.
The HTTP route is registered via the VM107 auto-discovery mechanism at:
    api/v1/agents/macro_historical_analyst/invoke.py

This file exists to satisfy the plan artifact requirement for a router.py
in the agent package directory and to document the invocation contract.

Invocation contract:
    POST /api/v1/agents/macro_historical_analyst/invoke
    Headers: X-API-KEY: <vm107 service key>
    Body: {
        "envelope": { ... vm102_event_study envelope ... },
        "result": { ... event-study result with curves ... },
        "indicator_name": "Consumer Price Index",
        "asset_names": ["Gold", "USD", "S&P 500"]
    }
    Response 200: {
        "envelope": {
            "tool_id": "vm107_macro_historical_analyst",
            "confidence": "high"|"medium"|"low",
            "provenance": {"sample_size": N, "period": "...", "indicator_id": "..."},
            "latency_ms": int
        },
        "result": {"narrative": "..."} | null,
        "error": null | {"code": "MissingCitations", "meta": {...}}
    }

Plan 86-08 registers the VM100 dispatch bridge (historicalAnalystDispatcher.js)
that POST-s to this endpoint on macro_event_study_run window event.
Plan 86-09 registers the capability registry YAML for this agent.
"""
from agents.macro_historical_analyst.agent import MacroHistoricalAnalyst

__all__ = ["MacroHistoricalAnalyst"]
