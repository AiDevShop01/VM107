"""
SearchKnowledgeTool for semantic knowledge retrieval.

Searches knowledge_base_v2 collection with multi-vector named vector routing
and project+global scope filtering.
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
from tools.qdrant.query_router import QueryRouter
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")

# Rebuild models to resolve forward references
SearchKnowledgeResponse.model_rebuild()


class SearchKnowledgeTool(ContractTool):
    """
    Search knowledge base with semantic search.

    Searches knowledge_base_v2 collection with multi-vector named vector routing.
    Uses QueryRouter to determine which embedding space(s) to search, performs
    multi-space search with weighted deduplication, and applies diversity ranking.

    Retrieves global + project-scoped knowledge with diversity ranking.
    Follows ContractTool pattern with validate-request -> call -> validate-response.

    Dependencies (set via class attributes before agent calls tool):
        qdrant_client: QdrantClient instance
        embedding_service: EmbeddingService instance (must support bge-base-en-v1.5)
        ranking_config: Ranking configuration dict from config/ranking.yaml
    """

    # Class-level dependencies (set during agent initialization)
    qdrant_client = None
    embedding_service = None
    ranking_config = None

    def __init__(self, *args, **kwargs):
        """Initialize SearchKnowledgeTool."""
        super().__init__(*args, **kwargs)
        self.query_router = QueryRouter()

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
        Search knowledge_base_v2 collection with multi-vector named vector routing.

        Uses QueryRouter to determine which embedding space(s) to search based on
        query intent. For multi-space queries, searches each space, merges results
        with weighted scoring, deduplicates by point ID (keeping highest score),
        and applies diversity-weighted ranking.

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
            # Embed query (single embedding used for all spaces)
            # Handle both single-text and batch embedding interfaces
            if hasattr(self.embedding_service, 'embed'):
                # BgeEmbeddingAdapter interface (returns EmbedResponse)
                embed_response = await self.embedding_service.embed([request.query])
                query_vector = embed_response.embeddings[0]
            else:
                # Fallback for other embedding service interfaces
                query_vector = await self.embedding_service.embed(request.query)

            # Use QueryRouter to determine which embedding space(s) to search
            search_spaces = self.query_router.get_search_spaces(request.query)

            # Get ranking config (try knowledge_v2 first, fallback to knowledge)
            ranking_cfg = self.ranking_config.get("knowledge_v2", self.ranking_config.get("knowledge", {}))
            semantic_weight = ranking_cfg.get("semantic_weight", 0.7)
            diversity_weight = ranking_cfg.get("diversity_weight", 0.15)
            max_results_per_space = ranking_cfg.get("max_results_per_space", 10)

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

            # Multi-space search: search each space and merge results
            all_results = {}  # {point_id: (score, hit)}
            spaces_searched = []

            for space_info in search_spaces:
                space_name = space_info["space"]
                space_weight = space_info["weight"]
                spaces_searched.append(space_name)

                # Search Qdrant with named vector
                search_results = self.qdrant_client.search(
                    collection_name="knowledge_base_v2",
                    query_vector=(space_name, query_vector),  # Named vector tuple
                    query_filter=query_filter,
                    limit=max_results_per_space
                )

                # Process results with space weight
                for hit in search_results:
                    point_id = hit.id
                    weighted_score = hit.score * space_weight

                    # Keep highest weighted score for each point ID (deduplication)
                    if point_id not in all_results or weighted_score > all_results[point_id][0]:
                        all_results[point_id] = (weighted_score, hit)

            # Convert to list and sort by weighted score descending
            sorted_results = sorted(
                all_results.values(),
                key=lambda x: x[0],
                reverse=True
            )

            # Apply diversity-weighted ranking and take top_k
            final_results = []
            for idx, (weighted_score, hit) in enumerate(sorted_results[:request.top_k]):
                # Diversity boost decreases with rank
                diversity_boost = 1.0 - (idx * 0.1)  # 1.0, 0.9, 0.8, etc.
                final_score = (
                    weighted_score * semantic_weight +
                    diversity_boost * diversity_weight
                )

                result_dict = {
                    **hit.payload,
                    "score": final_score
                }
                final_results.append(result_dict)

            # Build RetrievalMetadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            # Get embedding model info
            if hasattr(self.embedding_service, 'MODEL_NAME'):
                model_name = self.embedding_service.MODEL_NAME
                dimension = self.embedding_service.VECTOR_DIM
            elif hasattr(self.embedding_service, 'model_name'):
                model_name = self.embedding_service.model_name
                dimension = self.embedding_service.dimension
            else:
                model_name = "unknown"
                dimension = 768

            metadata = {
                "query_hash": query_hash,
                "project_id": request.project_id,
                "collections": ["knowledge_base_v2"],
                "total_hits": len(all_results),
                "result_count": len(final_results),
                "latency_ms": latency_ms,
                "embedding_model": model_name,
                "embedding_dimension": dimension
            }

            # Emit structured log
            logger.info(json.dumps({
                "event": "qdrant_search",
                "collection": "knowledge_base_v2",
                "spaces_searched": spaces_searched,
                "project": request.project_id,
                "top_k": request.top_k,
                "result_count": len(final_results),
                "latency_ms": latency_ms,
                "timestamp": timestamp
            }))

            return {"results": final_results, "metadata": metadata}

        except Exception as e:
            # Graceful degradation - return empty results
            logger.error(json.dumps({
                "event": "qdrant_search",
                "collection": "knowledge_base_v2",
                "status": "error",
                "error": str(e),
                "timestamp": timestamp
            }))

            # Return empty results with metadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            # Get embedding model info
            if hasattr(self.embedding_service, 'MODEL_NAME'):
                model_name = self.embedding_service.MODEL_NAME
                dimension = self.embedding_service.VECTOR_DIM
            elif hasattr(self.embedding_service, 'model_name'):
                model_name = self.embedding_service.model_name
                dimension = self.embedding_service.dimension
            else:
                model_name = "unknown"
                dimension = 768

            return {
                "results": [],
                "metadata": {
                    "query_hash": query_hash,
                    "project_id": request.project_id,
                    "collections": ["knowledge_base_v2"],
                    "total_hits": 0,
                    "result_count": 0,
                    "latency_ms": latency_ms,
                    "embedding_model": model_name,
                    "embedding_dimension": dimension
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
