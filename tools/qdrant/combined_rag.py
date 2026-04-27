"""
CombinedRAGTool for merged memory + knowledge retrieval.

Searches both agent_memory and knowledge_base_v2 collections,
merges results into token-bounded combined context for LLM prompts.
Uses multi-vector search with QueryRouter for knowledge retrieval.
"""
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone

from fingpt_core.contracts import (
    CombinedRAGRequest,
    CombinedRAGResponse,
    KnowledgeItem,
    MemoryItem,
    RetrievalMetadata,
)
from helpers.tool import Response
from qdrant_client.models import FieldCondition, Filter, MatchValue
from tools.qdrant.query_router import QueryRouter
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")

# Rebuild models to resolve forward references
CombinedRAGResponse.model_rebuild()


class CombinedRAGTool(ContractTool):
    """
    Search both memory and knowledge with combined context.

    Searches agent_memory and knowledge_base_v2 collections,
    applies respective ranking (memory=recency-weighted, knowledge=multi-vector diversity-weighted),
    and builds token-bounded combined context for LLM insertion.

    Uses QueryRouter for intent-driven multi-vector knowledge search.

    Dependencies (set via class attributes before agent calls tool):
        qdrant_client: QdrantClient instance
        embedding_service: EmbeddingService instance
        ranking_config: Ranking configuration dict from config/ranking.yaml
    """

    # Class-level dependencies (set during agent initialization)
    qdrant_client = None
    embedding_service = None
    ranking_config = None

    # Outcome weights for memory ranking
    outcome_weights = {
        "win": 0.10,
        "loss": 0.05,
        "missed": 0.03,
        "invalid": 0.0,
        "unknown": 0.0
    }

    def __init__(self, *args, **kwargs):
        """Initialize CombinedRAGTool."""
        super().__init__(*args, **kwargs)
        self.query_router = QueryRouter()

    def _validate_request(self, args: dict) -> CombinedRAGRequest:
        """
        Validate request args against CombinedRAGRequest contract.

        Args:
            args: Tool arguments from agent

        Returns:
            Validated CombinedRAGRequest

        Raises:
            ContractValidationError: If validation fails
        """
        return CombinedRAGRequest(**args)

    async def _call_vm(self, request: CombinedRAGRequest) -> dict:
        """
        Search both agent_memory and knowledge_base_v2 collections.

        Embeds query once (shared), searches both collections, applies
        respective ranking (memory=recency-weighted, knowledge=multi-vector diversity-weighted),
        builds token-bounded combined context.

        Args:
            request: Validated CombinedRAGRequest

        Returns:
            Dict with "memory_results", "knowledge_results", "combined_context", "metadata"

        Raises:
            Exception: On Qdrant errors (caught by graceful degradation)
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            # Embed query once (shared between both searches)
            # Handle both single-text and batch embedding interfaces
            if hasattr(self.embedding_service, 'embed'):
                # BgeEmbeddingAdapter interface (returns EmbedResponse)
                embed_response = await self.embedding_service.embed([request.query])
                query_vector = embed_response.embeddings[0]
            else:
                # Fallback for other embedding service interfaces
                query_vector = await self.embedding_service.embed(request.query)

            # Search agent_memory
            memory_results = await self._search_memory(
                query_vector,
                request.project_id,
                request.memory_top_k
            )

            # Search knowledge_base
            knowledge_results = await self._search_knowledge(
                query_vector,
                request.project_id,
                request.knowledge_top_k
            )

            # Build combined context
            combined_context = self._build_combined_context(
                memory_results,
                knowledge_results,
                request.max_context_tokens
            )

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
                "collections": ["agent_memory", "knowledge_base_v2"],
                "total_hits": len(memory_results) + len(knowledge_results),
                "result_count": len(memory_results) + len(knowledge_results),
                "latency_ms": latency_ms,
                "embedding_model": model_name,
                "embedding_dimension": dimension
            }

            # Emit structured log
            logger.info(json.dumps({
                "event": "combined_rag_search",
                "project": request.project_id,
                "memory_count": len(memory_results),
                "knowledge_count": len(knowledge_results),
                "latency_ms": latency_ms,
                "timestamp": timestamp
            }))

            return {
                "memory_results": memory_results,
                "knowledge_results": knowledge_results,
                "combined_context": combined_context,
                "metadata": metadata
            }

        except Exception as e:
            # Graceful degradation - return empty results
            logger.error(json.dumps({
                "event": "combined_rag_search",
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
                "memory_results": [],
                "knowledge_results": [],
                "combined_context": "No relevant context found.",
                "metadata": {
                    "query_hash": query_hash,
                    "project_id": request.project_id,
                    "collections": ["agent_memory", "knowledge_base_v2"],
                    "total_hits": 0,
                    "result_count": 0,
                    "latency_ms": latency_ms,
                    "embedding_model": model_name,
                    "embedding_dimension": dimension
                }
            }

    async def _search_memory(self, query_vector: list[float], project_id: str, top_k: int) -> list[dict]:
        """
        Search agent_memory collection with recency-weighted ranking.

        Args:
            query_vector: Embedded query vector
            project_id: Project identifier
            top_k: Maximum results to return

        Returns:
            List of memory result dicts with scores
        """
        # Build mandatory project filter
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="project",
                    match=MatchValue(value=project_id)
                )
            ]
        )

        # Search Qdrant
        search_results = self.qdrant_client.search(
            collection_name="agent_memory",
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k * 2  # Fetch extra for re-ranking
        )

        # Apply recency-weighted ranking
        semantic_weight = self.ranking_config["memory"]["semantic_weight"]
        recency_weight = self.ranking_config["memory"]["recency_weight"]
        outcome_weight = self.ranking_config["memory"]["outcome_weight"]
        recency_decay_hours = self.ranking_config["memory"]["recency_decay_hours"]

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
        return [r[1] for r in ranked_results[:top_k]]

    async def _search_knowledge(self, query_vector: list[float], project_id: str, top_k: int) -> list[dict]:
        """
        Search knowledge_base_v2 collection with multi-vector diversity-weighted ranking.

        Uses QueryRouter to determine which embedding space(s) to search based on
        query intent (extracted from CombinedRAGRequest.query). Performs multi-space
        search with weighted deduplication.

        Args:
            query_vector: Embedded query vector
            project_id: Project identifier
            top_k: Maximum results to return

        Returns:
            List of knowledge result dicts with scores
        """
        # Get query from args for intent classification
        query_text = self.args.get("query", "")
        search_spaces = self.query_router.get_search_spaces(query_text)

        # Get ranking config (try knowledge_v2 first, fallback to knowledge)
        ranking_cfg = self.ranking_config.get("knowledge_v2", self.ranking_config.get("knowledge", {}))
        semantic_weight = ranking_cfg.get("semantic_weight", 0.7)
        diversity_weight = ranking_cfg.get("diversity_weight", 0.15)
        max_results_per_space = ranking_cfg.get("max_results_per_space", 10)

        # Build OR filter: (project == current_project OR project == "global")
        query_filter = Filter(
            should=[
                FieldCondition(
                    key="project",
                    match=MatchValue(value=project_id)
                ),
                FieldCondition(
                    key="project",
                    match=MatchValue(value="global")
                )
            ]
        )

        # Multi-space search: search each space and merge results
        all_results = {}  # {point_id: (score, hit)}

        for space_info in search_spaces:
            space_name = space_info["space"]
            space_weight = space_info["weight"]

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
        for idx, (weighted_score, hit) in enumerate(sorted_results[:top_k]):
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

        return final_results

    def _build_combined_context(
        self,
        memory_results: list[dict],
        knowledge_results: list[dict],
        max_context_tokens: int
    ) -> str:
        """
        Build combined context string within token budget.

        Memory results appear first (more relevant to current task),
        then knowledge results. Context trimmed by dropping lowest-scored
        items until within token budget.

        Args:
            memory_results: Memory search results
            knowledge_results: Knowledge search results
            max_context_tokens: Maximum tokens for combined context

        Returns:
            Combined context string
        """
        if not memory_results and not knowledge_results:
            return "No relevant context found."

        # Build sections
        sections = []

        if memory_results:
            memory_lines = ["=== AGENT MEMORY ==="]
            for idx, item in enumerate(memory_results, 1):
                summary = item.get("summary", "")
                score = item.get("score", 0)
                memory_lines.append(f"[{idx}] {summary} (Score: {score:.3f})")
            sections.append("\n".join(memory_lines))

        if knowledge_results:
            knowledge_lines = ["=== KNOWLEDGE ==="]
            for idx, item in enumerate(knowledge_results, 1):
                text = item.get("text", "")
                title = item.get("title", "Unknown")
                score = item.get("score", 0)
                knowledge_lines.append(f"[{idx}] {text}\n    Source: {title} (Score: {score:.3f})")
            sections.append("\n".join(knowledge_lines))

        combined = "\n\n".join(sections)

        # Token count approximation: word_count * 1.3
        word_count = len(combined.split())
        approx_tokens = int(word_count * 1.3)

        # If within budget, return as-is
        if approx_tokens <= max_context_tokens:
            return combined

        # Trim by dropping lowest-scored items
        all_items = []
        for item in memory_results:
            all_items.append(("memory", item))
        for item in knowledge_results:
            all_items.append(("knowledge", item))

        # Sort by score descending
        all_items.sort(key=lambda x: x[1].get("score", 0), reverse=True)

        # Rebuild context with top items until within budget
        trimmed_memory = []
        trimmed_knowledge = []

        for item_type, item in all_items:
            if item_type == "memory":
                trimmed_memory.append(item)
            else:
                trimmed_knowledge.append(item)

            # Rebuild context
            trimmed = self._build_combined_context(
                trimmed_memory,
                trimmed_knowledge,
                max_context_tokens
            )

            word_count = len(trimmed.split())
            approx_tokens = int(word_count * 1.3)

            if approx_tokens > max_context_tokens:
                # Remove last item and return
                if item_type == "memory":
                    trimmed_memory.pop()
                else:
                    trimmed_knowledge.pop()
                return self._build_combined_context(
                    trimmed_memory,
                    trimmed_knowledge,
                    max_context_tokens
                )

        return combined

    def _validate_response(self, data: dict) -> CombinedRAGResponse:
        """
        Validate response data against CombinedRAGResponse contract.

        Args:
            data: Raw response dict from _call_vm

        Returns:
            Validated CombinedRAGResponse

        Raises:
            ContractValidationError: If validation fails
        """
        return CombinedRAGResponse(**data)

    def _format_response(self, contract: CombinedRAGResponse) -> Response:
        """
        Format validated response for agent.

        Returns combined_context directly as message with metadata summary.

        Args:
            contract: Validated CombinedRAGResponse

        Returns:
            Response object for agent
        """
        # Build metadata summary
        result_count = len(contract.memory_results) + len(contract.knowledge_results)
        collections = ", ".join(contract.metadata.collections)
        latency_ms = contract.metadata.latency_ms

        metadata_summary = f"\n\n---\n{result_count} results from {collections}, {latency_ms}ms"

        message = contract.combined_context + metadata_summary
        return Response(message=message, break_loop=False)
