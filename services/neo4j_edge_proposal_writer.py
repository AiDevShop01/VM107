"""Phase 89 Wave 4 — Neo4j shadow edge proposal writer.

Thin adapter that calls the vm105.neo4j_macro_graph_walker.propose_edge tool
with edge_lifecycle_state='shadow' (Decision 8).

Per project lock: NEO4J_URI from env — NO fallback default.

This module is the production implementation. Tests use the
neo4j_macro_graph_double conftest fixture instead.
"""
from __future__ import annotations

import logging
import os
from uuid import UUID

logger = logging.getLogger(__name__)


def _required(key: str) -> str:
    """Return env var value or raise RuntimeError if missing (fail-fast)."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast (Phase 89 env-driven config). "
            f"Set {key} in your environment before starting."
        )
    return v


class Neo4jEdgeProposalWriter:
    """Writes shadow edges to the Neo4j macro graph.

    Uses the vm105.neo4j_macro_graph_walker tool via HTTP or the graph-walker
    interface (depending on how VM105 is exposed in the current deployment).

    Env vars required (no fallback defaults per project lock):
      NEO4J_URI  — e.g. bolt://192.168.1.105:7687

    Args:
        neo4j_uri: Override the NEO4J_URI env var (for testing only).
    """

    def __init__(self, neo4j_uri: str | None = None) -> None:
        self._uri = neo4j_uri or _required("NEO4J_URI")

    def propose_edge(
        self,
        from_node: str,
        to_node: str,
        edge_type: str,
        strength: float = 0.0,
        confidence: float = 0.0,
        edge_lifecycle_state: str = "shadow",
        proposal_id: str | None = None,
        **extra,
    ) -> str:
        """Write a shadow edge to the Neo4j macro graph.

        Decision 8: edge_lifecycle_state is always 'shadow' in Phase 89.
        The edge remains shadow until a human reviewer promotes it via the
        Phase 53 governance UI.

        Args:
            from_node: Source indicator or asset node ID.
            to_node: Target indicator or asset node ID.
            edge_type: Edge type ("leads_by_months" or "correlated_with").
            strength: Correlation coefficient.
            confidence: Agent confidence [0.0, 1.0].
            edge_lifecycle_state: Always "shadow" in Phase 89 (Decision 8).
            proposal_id: UUID string of the EdgeProposal artifact.

        Returns:
            Neo4j edge UUID string (authoritative record).
        """
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(self._uri)
            edge_uuid = proposal_id or str(__import__("uuid").uuid4())

            with driver.session() as session:
                session.run(
                    """
                    MERGE (a:MacroNode {id: $from_node})
                    MERGE (b:MacroNode {id: $to_node})
                    CREATE (a)-[r:MACRO_RELATIONSHIP {
                        edge_uuid: $edge_uuid,
                        edge_type: $edge_type,
                        strength: $strength,
                        confidence: $confidence,
                        edge_lifecycle_state: $lifecycle_state,
                        proposal_id: $proposal_id
                    }]->(b)
                    """,
                    from_node=from_node,
                    to_node=to_node,
                    edge_uuid=edge_uuid,
                    edge_type=edge_type,
                    strength=strength,
                    confidence=confidence,
                    lifecycle_state=edge_lifecycle_state,
                    proposal_id=proposal_id or edge_uuid,
                )

            driver.close()

            logger.info({
                "event": "phase89_neo4j_shadow_edge_created",
                "edge_uuid": edge_uuid,
                "from_node": from_node,
                "to_node": to_node,
                "edge_type": edge_type,
                "lifecycle_state": edge_lifecycle_state,
            })
            return edge_uuid

        except Exception as exc:
            logger.error({
                "event": "phase89_neo4j_write_error",
                "from_node": from_node,
                "to_node": to_node,
                "error": str(exc),
            })
            raise
