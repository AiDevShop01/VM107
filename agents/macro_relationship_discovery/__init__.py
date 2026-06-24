"""Phase 89.2 — macro_relationship_discovery scheduled background agent.

Nightly 03:00 UTC scan invoked by Dagster's macro_discovery_nightly_schedule.
Orchestrates the VM107/core/discovery library (CorrelationScanner + EdgeProposer
+ ThroughputGovernor + Neo4jEdgeProposalWriter) over a fixed list of
(indicator, asset) pairs from scan_pairs.DEFAULT_SCAN_PAIRS.

Invocation contract:
    POST /api/v1/agents/macro_relationship_discovery/invoke
    Body: {"message": str, "run_mode": str}
    Response: {"proposals_created": int, "scan_duration_s": float, "throughput_action": str}

Locked decisions (89.2-RESEARCH.md):
- VM102 endpoints are indicator-vs-asset only — DEFAULT_SCAN_PAIRS = (FRED_code, asset_slug)
- Agent reads tightened r_min from macro_discovery_throughput on startup
- All env vars fail-fast at .run() time, never at module import
"""
from agents.macro_relationship_discovery.agent import MacroRelationshipDiscovery

__all__ = ["MacroRelationshipDiscovery"]
