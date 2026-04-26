"""
SearchMemoryTool for semantic memory retrieval.

Searches agent_memory collection with mandatory project filtering
and recency-weighted ranking.
"""
import hashlib
import json
import logging
import math
import time
from datetime import datetime

from fingpt_core.contracts import (
    MemoryItem,
    RetrievalMetadata,
    SearchMemoryRequest,
    SearchMemoryResponse,
)
from helpers.tool import Response
from qdrant_client.models import FieldCondition, Filter, MatchValue
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")

# Rebuild models to resolve forward references
SearchMemoryResponse.model_rebuild()


class SearchMemoryTool(ContractTool):
    """
    Search agent memory with semantic search.

    Retrieves project-scoped memory with recency-weighted ranking.
    Follows ContractTool pattern with validate-request -> call -> validate-response.

    Dependencies (set via class attributes before agent calls tool):
        qdrant_client: QdrantClient instance
        embedding_service: EmbeddingService instance
        ranking_config: Ranking configuration dict from config/ranking.yaml
    """

    # Class-level dependencies (set during agent initialization)
    qdrant_client = None
    embedding_service = None
    ranking_config = None

    # Outcome weights for ranking
    outcome_weights = {
        "win": 0.10,
        "loss": 0.05,
        "missed": 0.03,
        "invalid": 0.0,
        "unknown": 0.0
    }

    def __init__(self, *args, **kwargs):
        """Initialize SearchMemoryTool."""
        super().__init__(*args, **kwargs)

    def _validate_request(self, args: dict) -> SearchMemoryRequest:
        """
        Validate request args against SearchMemoryRequest contract.

        Args:
            args: Tool arguments from agent

        Returns:
            Validated SearchMemoryRequest

        Raises:
            ContractValidationError: If validation fails
        """
        return SearchMemoryRequest(**args)

    async def _call_vm(self, request: SearchMemoryRequest) -> dict:
        """
        Search agent_memory collection with mandatory project filter.

        Embeds query, builds MUST filter (project == current_project),
        applies optional area filter, searches Qdrant, applies
        recency-weighted ranking with outcome boost, and returns
        results with RetrievalMetadata.

        Args:
            request: Validated SearchMemoryRequest

        Returns:
            Dict with "results" and "metadata" keys

        Raises:
            Exception: On Qdrant errors (caught by graceful degradation)
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            # Embed query
            query_vector = await self.embedding_service.embed(request.query)

            # Build filter: MANDATORY project filter
            must_conditions = [
                FieldCondition(
                    key="project",
                    match=MatchValue(value=request.project_id)
                )
            ]

            # Add area filter if provided
            if request.area:
                must_conditions.append(
                    FieldCondition(
                        key="area",
                        match=MatchValue(value=request.area)
                    )
                )

            query_filter = Filter(must=must_conditions)

            # Search Qdrant
            search_results = self.qdrant_client.search(
                collection_name="agent_memory",
                query_vector=query_vector,
                query_filter=query_filter,
                limit=request.top_k * 2  # Fetch extra for re-ranking
            )

            # Apply recency-weighted ranking
            semantic_weight = self.ranking_config["memory"]["semantic_weight"]
            recency_weight = self.ranking_config["memory"]["recency_weight"]
            outcome_weight = self.ranking_config["memory"]["outcome_weight"]
            recency_decay_hours = self.ranking_config["memory"]["recency_decay_hours"]

            from datetime import timezone
            now = datetime.now(timezone.utc)
            ranked_results = []

            for hit in search_results:
                # Calculate recency score
                memory_timestamp = datetime.fromisoformat(
                    hit.payload.get("timestamp", "").replace("Z", "+00:00")
                )
                hours_since = (now - memory_timestamp).total_seconds() / 3600
                recency_score = math.exp(-hours_since / recency_decay_hours)

                # Calculate outcome boost
                outcome = hit.payload.get("outcome")
                outcome_boost = self.outcome_weights.get(outcome, 0.0) if outcome else 0.0

                # Calculate final score
                final_score = (
                    hit.score * semantic_weight +
                    recency_score * recency_weight +
                    outcome_boost * outcome_weight
                )

                result_dict = {
                    **hit.payload,
                    "score": final_score
                }
                ranked_results.append((final_score, result_dict))

            # Re-sort by final score and take top_k
            ranked_results.sort(key=lambda x: x[0], reverse=True)
            results = [r[1] for r in ranked_results[:request.top_k]]

            # Build RetrievalMetadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            metadata = {
                "query_hash": query_hash,
                "project_id": request.project_id,
                "collections": ["agent_memory"],
                "total_hits": len(search_results),
                "result_count": len(results),
                "latency_ms": latency_ms,
                "embedding_model": self.embedding_service.model_name,
                "embedding_dimension": self.embedding_service.dimension
            }

            # Emit structured log
            logger.info(json.dumps({
                "event": "qdrant_search",
                "collection": "agent_memory",
                "project": request.project_id,
                "top_k": request.top_k,
                "result_count": len(results),
                "latency_ms": latency_ms,
                "timestamp": timestamp
            }))

            return {"results": results, "metadata": metadata}

        except Exception as e:
            # Graceful degradation - return empty results
            logger.error(json.dumps({
                "event": "qdrant_search",
                "collection": "agent_memory",
                "status": "error",
                "error": str(e),
                "timestamp": timestamp
            }))

            # Return empty results with metadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "results": [],
                "metadata": {
                    "query_hash": query_hash,
                    "project_id": request.project_id,
                    "collections": ["agent_memory"],
                    "total_hits": 0,
                    "result_count": 0,
                    "latency_ms": latency_ms,
                    "embedding_model": self.embedding_service.model_name,
                    "embedding_dimension": self.embedding_service.dimension
                }
            }

    def _validate_response(self, data: dict) -> SearchMemoryResponse:
        """
        Validate response data against SearchMemoryResponse contract.

        Args:
            data: Raw response dict from _call_vm

        Returns:
            Validated SearchMemoryResponse

        Raises:
            ContractValidationError: If validation fails
        """
        return SearchMemoryResponse(**data)

    def _format_response(self, contract: SearchMemoryResponse) -> Response:
        """
        Format validated response for agent.

        Builds readable context with area and type:
        [N] {summary[:200]}... Area: {area} Type: {type} Score: {score:.3f}

        Args:
            contract: Validated SearchMemoryResponse

        Returns:
            Response object for agent
        """
        if not contract.results:
            return Response(
                message="No memory found for your query.",
                break_loop=False
            )

        lines = []
        for idx, item in enumerate(contract.results, 1):
            summary_preview = item.summary[:200] + "..." if len(item.summary) > 200 else item.summary
            area_str = item.area or "N/A"
            score_str = f"{item.score:.3f}" if item.score else "N/A"
            lines.append(
                f"[{idx}] {summary_preview}\n"
                f"    Area: {area_str} Type: {item.type} Score: {score_str}"
            )

        message = "\n\n".join(lines)
        return Response(message=message, break_loop=False)
