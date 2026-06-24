"""Phase 89.2 Plan 03 Task 1 placeholder — Task 2 implements MacroRelationshipDiscovery.

This stub exists only so the package ``__init__.py`` resolves between Task 1
and Task 2. The real class lands in Task 2 (full orchestration of
CorrelationScanner + EdgeProposer + ThroughputGovernor + Neo4jEdgeProposalWriter).
"""
from __future__ import annotations


class MacroRelationshipDiscovery:
    """Placeholder — implemented in Plan 03 Task 2."""

    agent_id = "vm107.macro_relationship_discovery"

    def run(self, message: str = "run nightly scan", run_mode: str = "scheduled") -> dict:
        raise NotImplementedError(
            "Plan 03 Task 2 implements .run() — this stub exists only for Task 1 package import."
        )
