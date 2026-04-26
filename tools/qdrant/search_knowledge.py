"""
SearchKnowledgeTool for semantic knowledge retrieval.

Searches knowledge_base collection with project+global scope filtering.
"""
import hashlib
import json
import logging
import time
from datetime import datetime

from fingpt_core.contracts import (
    KnowledgeItem,
    RetrievalMetadata,
    SearchKnowledgeRequest,
    SearchKnowledgeResponse,
)
from helpers.tool import Response
from qdrant_client.models import FieldCondition, Filter, MatchValue
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")

# Rebuild models to resolve forward references
SearchKnowledgeResponse.model_rebuild()


class SearchKnowledgeTool(ContractTool):
    """
    Search knowledge base with semantic search.

    Retrieves global + project-scoped knowledge with diversity ranking.
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

    def __init__(self, *args, **kwargs):
        """Initialize SearchKnowledgeTool."""
        super().__init__(*args, **kwargs)

    def _validate_request(self, args: dict) -> SearchKnowledgeRequest:
        """
        Validate request args against SearchKnowledgeRequest contract.

        Args:
            args: Tool arguments from agent

        Returns:
            Validated SearchKnowledgeRequest

        Raises:
            ContractValidationError: If validation fails
        """
        return SearchKnowledgeRequest(**args)

    async def _call_vm(self, request: SearchKnowledgeRequest) -> dict:
        """
        Search knowledge_base collection with project+global filter.

        Embeds query, builds OR filter (project == current OR project == "global"),
        applies optional topic/source_type filters, searches Qdrant, applies
        diversity-weighted ranking, and returns results with RetrievalMetadata.

        Args:
            request: Validated SearchKnowledgeRequest

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

            # Build filter: (project == current_project OR project == "global")
            filter_conditions = {
                "should": [
                    FieldCondition(
                        key="project",
                        match=MatchValue(value=request.project_id)
                    ),
                    FieldCondition(
                        key="project",
                        match=MatchValue(value="global")
                    )
                ]
            }

            # Add must conditions for topic/source_type if provided
            must_conditions = []
            if request.topic:
                must_conditions.append(
                    FieldCondition(
                        key="topic",
                        match=MatchValue(value=request.topic)
                    )
                )
            if request.source_type:
                must_conditions.append(
                    FieldCondition(
                        key="source_type",
                        match=MatchValue(value=request.source_type)
                    )
                )

            if must_conditions:
                filter_conditions["must"] = must_conditions

            query_filter = Filter(**filter_conditions)

            # Search Qdrant
            search_results = self.qdrant_client.search(
                collection_name="knowledge_base",
                query_vector=query_vector,
                query_filter=query_filter,
                limit=request.top_k
            )

            # Apply diversity-weighted ranking
            semantic_weight = self.ranking_config["knowledge"]["semantic_weight"]
            diversity_weight = self.ranking_config["knowledge"]["diversity_weight"]

            results = []
            for idx, hit in enumerate(search_results):
                # Diversity boost decreases with rank
                diversity_boost = 1.0 - (idx * 0.1)  # 1.0, 0.9, 0.8, etc.
                final_score = (
                    hit.score * semantic_weight +
                    diversity_boost * diversity_weight
                )

                result_dict = {
                    **hit.payload,
                    "score": final_score
                }
                results.append(result_dict)

            # Build RetrievalMetadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            metadata = {
                "query_hash": query_hash,
                "project_id": request.project_id,
                "collections": ["knowledge_base"],
                "total_hits": len(search_results),
                "result_count": len(results),
                "latency_ms": latency_ms,
                "embedding_model": self.embedding_service.model_name,
                "embedding_dimension": self.embedding_service.dimension
            }

            # Emit structured log
            logger.info(json.dumps({
                "event": "qdrant_search",
                "collection": "knowledge_base",
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
                "collection": "knowledge_base",
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
                    "collections": ["knowledge_base"],
                    "total_hits": 0,
                    "result_count": 0,
                    "latency_ms": latency_ms,
                    "embedding_model": self.embedding_service.model_name,
                    "embedding_dimension": self.embedding_service.dimension
                }
            }

    def _validate_response(self, data: dict) -> SearchKnowledgeResponse:
        """
        Validate response data against SearchKnowledgeResponse contract.

        Args:
            data: Raw response dict from _call_vm

        Returns:
            Validated SearchKnowledgeResponse

        Raises:
            ContractValidationError: If validation fails
        """
        return SearchKnowledgeResponse(**data)

    def _format_response(self, contract: SearchKnowledgeResponse) -> Response:
        """
        Format validated response for agent.

        Builds readable context with source attribution:
        [N] {text[:200]}... Source: {title} ({source_type}) Score: {score:.3f}

        Args:
            contract: Validated SearchKnowledgeResponse

        Returns:
            Response object for agent
        """
        if not contract.results:
            return Response(
                message="No knowledge found for your query.",
                break_loop=False
            )

        lines = []
        for idx, item in enumerate(contract.results, 1):
            text_preview = item.text[:200] + "..." if len(item.text) > 200 else item.text
            source_info = f"{item.title or 'Unknown'} ({item.source_type})"
            score_str = f"{item.score:.3f}" if item.score else "N/A"
            lines.append(
                f"[{idx}] {text_preview}\n"
                f"    Source: {source_info} Score: {score_str}"
            )

        message = "\n\n".join(lines)
        return Response(message=message, break_loop=False)
