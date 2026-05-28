"""Phase 70.5 Plan 07 — proxy implementations for the 16 facade tools.

Each proxy module in this package makes a typed HTTP call to a remote VM's
inter-VM endpoint, returns a typed ToolPayload, and lets the VM107 dispatcher
wrap it into a ToolResultEnvelope.

VM107 is the canonical epistemic authority boundary (Decision 18):
- Remote VMs return ToolPayload (typed data only)
- VM107 constructs confidence / freshness / registry_snapshot_hash / citations

Discovery: tool_resolver.py discovers each proxy module via the YAML's
location.source field (e.g. VM107/tools/proxies/vm100_analytics_calendar.py
→ tools.proxies.vm100_analytics_calendar).
"""
