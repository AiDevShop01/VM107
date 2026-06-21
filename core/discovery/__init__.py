"""Phase 89 Wave 4 — macro relationship discovery package.

Modules:
  correlation_scanner   — sweeps (indicator, asset) + (indicator, indicator) pairs
                          over a 12-month window; applies r/p/n thresholds from
                          the agent profile YAML (Decision 4, REQ-89-4).
  edge_proposer         — builds EdgeProposal contracts; writes Neo4j FIRST then
                          Postgres (Pitfall 7); emits Phase 91 alert candidates
                          via the SHARED helper from Plan 03.
  throughput_governor   — weekly proposal counter + threshold-tightening logic
                          (Decision 4: <1/week → warn, >10/week → tighten).
"""
