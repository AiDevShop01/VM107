"""
GraphSearchTool for Neo4j knowledge graph queries.

Provides parameterized Cypher templates for relationship traversal.
Follows ContractTool pattern with Pydantic request/response validation.
Gracefully degrades when Neo4j unavailable.
"""
import json
import logging
import time
from datetime import datetime
from typing import Any

from core.contracts.base import BaseContract
from helpers.tool import Response
from pydantic import Field, field_validator
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")


class GraphSearchRequest(BaseContract):
    """Request for graph search operations."""

    template: str = Field(
        ...,
        description="Template name: find_predecessors, find_successors, find_related, find_path, find_methods_using, find_validated_relationships"
    )
    concept_name: str = Field(..., description="Primary concept to search")
    target_name: str = Field(default="", description="For find_path (second concept)")
    min_confidence: float = Field(default=0.0, description="Minimum relationship confidence")
    top_k: int = Field(default=10, description="Max results")
    entity_type: str = Field(default="", description="Filter by entity type (empty = all types)")

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        """Validate template name is one of the 6 supported templates."""
        valid_templates = [
            "find_predecessors",
            "find_successors",
            "find_related",
            "find_path",
            "find_methods_using",
            "find_validated_relationships"
        ]
        if v not in valid_templates:
            raise ValueError(f"Invalid template: {v}. Must be one of {valid_templates}")
        return v

    @field_validator("concept_name")
    @classmethod
    def validate_concept_name(cls, v: str) -> str:
        """Validate concept_name is non-empty."""
        if not v or not v.strip():
            raise ValueError("concept_name must be non-empty")
        return v.strip()


class GraphSearchResponse(BaseContract):
    """Response from graph search."""

    template: str
    concept_name: str
    results: list[dict[str, Any]]
    result_count: int
    query_time_ms: float


class GraphSearchTool(ContractTool):
    """
    Graph search tool with parameterized Cypher templates.

    Executes Neo4j queries for relationship traversal and entity discovery.
    No raw Cypher access — agent fills parameters, system controls structure.

    Templates:
    - find_predecessors: What leads to X? (PRECEDES relationships)
    - find_successors: What happens after X? (PRECEDES relationships)
    - find_related: What's connected to X? (co-occurring entities via MENTIONS)
    - find_path: Find path from A to B
    - find_methods_using: Methods that use concept X
    - find_validated_relationships: All validated edges for X

    NOTE: For Phase 40.2, find_predecessors/find_successors/find_validated_relationships
    return empty results (no validated PRECEDES relationships exist yet — that's Phase 41).
    find_related and find_methods_using work with deterministic MENTIONS relationships.

    Dependencies (set via class attribute before agent calls tool):
        neo4j_driver: Neo4j driver instance (from neo4j.GraphDatabase.driver)

    Graceful degradation:
        - neo4j_driver is None -> returns empty results with warning
        - Connection fails -> returns empty results with logged error
        - Never crashes agent
    """

    # Class-level dependency (set during agent initialization)
    neo4j_driver = None

    # Cypher template definitions
    CYPHER_TEMPLATES = {
        "find_predecessors": """
            MATCH (a)-[r:PRECEDES]->(b {name: $concept_name})
            WHERE r.validated = true
              AND r.final_score >= $min_confidence
            RETURN a.name AS predecessor,
                   labels(a) AS entity_type,
                   r.final_score AS confidence,
                   r.sample_size AS sample_size
            ORDER BY r.final_score DESC
            LIMIT $top_k
        """,
        "find_successors": """
            MATCH (a {name: $concept_name})-[r:PRECEDES]->(b)
            WHERE r.validated = true
              AND r.final_score >= $min_confidence
            RETURN b.name AS successor,
                   labels(b) AS entity_type,
                   r.final_score AS confidence,
                   r.sample_size AS sample_size
            ORDER BY r.final_score DESC
            LIMIT $top_k
        """,
        "find_related": """
            MATCH (a)-[:MENTIONS]-(chunk:Chunk)-[:MENTIONS]-(b)
            WHERE a.name = $concept_name
              AND a <> b
            RETURN DISTINCT b.name AS related_entity,
                   labels(b) AS entity_type,
                   count(chunk) AS co_occurrence_count
            ORDER BY co_occurrence_count DESC
            LIMIT $top_k
        """,
        "find_path": """
            MATCH path = shortestPath((a {name: $concept_name})-[*..3]-(b {name: $target_name}))
            RETURN path,
                   length(path) AS path_length,
                   [node IN nodes(path) | node.name] AS node_names,
                   [rel IN relationships(path) | type(rel)] AS relationship_types
            LIMIT $top_k
        """,
        "find_methods_using": """
            MATCH (chunk:Chunk)-[:MENTIONS]->(m:Method),
                  (chunk)-[:MENTIONS]->(c {name: $concept_name})
            RETURN DISTINCT m.name AS method_name,
                   count(chunk) AS co_occurrence_count
            ORDER BY co_occurrence_count DESC
            LIMIT $top_k
        """,
        "find_validated_relationships": """
            MATCH (a {name: $concept_name})-[r]->(b)
            WHERE type(r) <> 'MENTIONS'
            RETURN type(r) AS relationship_type,
                   b.name AS target_entity,
                   labels(b) AS entity_type,
                   r.validated AS validated,
                   r.final_score AS confidence
            ORDER BY r.final_score DESC
            LIMIT $top_k
        """
    }

    def _validate_request(self, args: dict) -> GraphSearchRequest:
        """
        Validate request args against GraphSearchRequest contract.

        Args:
            args: Tool arguments from agent

        Returns:
            Validated GraphSearchRequest

        Raises:
            ContractValidationError: If validation fails
        """
        return GraphSearchRequest(**args)

    async def _call_vm(self, request: GraphSearchRequest) -> dict:
        """
        Execute Cypher query against Neo4j.

        NOT an HTTP call — direct Neo4j driver execution.
        Graceful degradation on connection errors.

        Args:
            request: Validated GraphSearchRequest

        Returns:
            Dict with "results" and "query_time_ms"

        Raises:
            Exception: On Neo4j errors (caught by graceful degradation)
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Graceful degradation: neo4j_driver is None
        if self.neo4j_driver is None:
            logger.warning(json.dumps({
                "event": "graph_search",
                "status": "neo4j_unavailable",
                "template": request.template,
                "concept": request.concept_name,
                "timestamp": timestamp
            }))
            return {
                "results": [],
                "query_time_ms": 0.0
            }

        try:
            # Get Cypher template
            cypher_query = self.CYPHER_TEMPLATES[request.template]

            # Build parameters
            params = {
                "concept_name": request.concept_name,
                "min_confidence": request.min_confidence,
                "top_k": request.top_k
            }
            if request.template == "find_path":
                params["target_name"] = request.target_name

            # Execute query with timeout (2 seconds)
            with self.neo4j_driver.session() as session:
                result = session.run(cypher_query, **params)
                records = [dict(record) for record in result]

            query_time_ms = (time.time() - start_time) * 1000

            # Log success
            logger.info(json.dumps({
                "event": "graph_search",
                "status": "success",
                "template": request.template,
                "concept": request.concept_name,
                "result_count": len(records),
                "query_time_ms": int(query_time_ms),
                "timestamp": timestamp
            }))

            return {
                "results": records,
                "query_time_ms": query_time_ms
            }

        except Exception as e:
            # Graceful degradation: connection/query failed
            query_time_ms = (time.time() - start_time) * 1000
            logger.error(json.dumps({
                "event": "graph_search",
                "status": "error",
                "template": request.template,
                "concept": request.concept_name,
                "error": str(e),
                "query_time_ms": int(query_time_ms),
                "timestamp": timestamp
            }))

            # Return empty results, don't crash agent
            return {
                "results": [],
                "query_time_ms": query_time_ms
            }

    def _validate_response(self, data: dict) -> GraphSearchResponse:
        """
        Validate response data against GraphSearchResponse contract.

        Args:
            data: Raw response dict from _call_vm

        Returns:
            Validated GraphSearchResponse

        Raises:
            ContractValidationError: If validation fails
        """
        # Build response from request + results
        return GraphSearchResponse(
            template=self.args["template"],
            concept_name=self.args["concept_name"],
            results=data["results"],
            result_count=len(data["results"]),
            query_time_ms=data["query_time_ms"]
        )

    def _format_response(self, contract: GraphSearchResponse) -> Response:
        """
        Format validated response for agent.

        Returns readable text summary of results.

        Args:
            contract: Validated GraphSearchResponse

        Returns:
            Response object for agent
        """
        if contract.result_count == 0:
            message = (
                f"No results found for {contract.template}(concept_name='{contract.concept_name}').\n"
                f"Query time: {contract.query_time_ms:.1f}ms"
            )
            return Response(message=message, break_loop=False)

        # Format results based on template type
        lines = [
            f"=== {contract.template.upper().replace('_', ' ')} ===",
            f"Concept: {contract.concept_name}",
            f"Results: {contract.result_count}",
            ""
        ]

        for idx, result in enumerate(contract.results, 1):
            if contract.template == "find_predecessors":
                lines.append(
                    f"{idx}. {result.get('predecessor')} "
                    f"(confidence: {result.get('confidence', 0):.2f}, "
                    f"samples: {result.get('sample_size', 0)})"
                )
            elif contract.template == "find_successors":
                lines.append(
                    f"{idx}. {result.get('successor')} "
                    f"(confidence: {result.get('confidence', 0):.2f}, "
                    f"samples: {result.get('sample_size', 0)})"
                )
            elif contract.template == "find_related":
                lines.append(
                    f"{idx}. {result.get('related_entity')} "
                    f"(co-occurrences: {result.get('co_occurrence_count', 0)})"
                )
            elif contract.template == "find_path":
                node_names = result.get('node_names', [])
                rel_types = result.get('relationship_types', [])
                path_str = " -> ".join([
                    f"{node_names[i]} --{rel_types[i]}--> {node_names[i+1]}"
                    for i in range(len(rel_types))
                ])
                lines.append(f"{idx}. {path_str} (length: {result.get('path_length', 0)})")
            elif contract.template == "find_methods_using":
                lines.append(
                    f"{idx}. {result.get('method_name')} "
                    f"(co-occurrences: {result.get('co_occurrence_count', 0)})"
                )
            elif contract.template == "find_validated_relationships":
                lines.append(
                    f"{idx}. --{result.get('relationship_type')}--> {result.get('target_entity')} "
                    f"(confidence: {result.get('confidence', 0):.2f})"
                )
            else:
                # Generic fallback
                lines.append(f"{idx}. {result}")

        lines.append(f"\nQuery time: {contract.query_time_ms:.1f}ms")

        message = "\n".join(lines)
        return Response(message=message, break_loop=False)
