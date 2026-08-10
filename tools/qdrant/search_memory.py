"""
SearchMemoryTool for semantic memory retrieval.

Searches agent_memory collection with mandatory project filtering
and recency-weighted ranking.
"""
import hashlib
import json
import logging
import time
from datetime import datetime

from fingpt_core.contracts import (
    MemoryItem,
    RetrievalMetadata,
    SearchMemoryRequest,
    SearchMemoryResponse,
)
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool

logger = logging.getLogger("fingpt.tools")

# Rebuild models to resolve forward references
SearchMemoryResponse.model_rebuild()


class SearchMemoryTool(ContractTool):
    """
    Search agent memory with semantic search.

    Retrieves project-scoped memory with semantic ranking.
    Follows ContractTool pattern with validate-request -> call -> validate-response.

    E-HIGH1 (Phase 137): SELF-ACQUIRES its agent_memory backend at call time via
    ``Memory.get(self.agent)`` (mirror tools/search_knowledge.py) — it no longer relies
    on the qdrant_client/embedding_service/ranking_config class attributes the runtime
    never injected (the same dead injected-attr pattern that made combined_rag.py return
    empty). The backend self-embeds (384-dim MiniLM) and applies the mandatory project
    filter internally. The class attributes below are retained ONLY for the legacy
    DI-mock harness; they are NOT read on the happy path.
    """

    # Legacy DI class attributes — retained for the old DI-mock harness only; NOT used
    # on the self-acquire happy path (E-HIGH1, Phase 137).
    qdrant_client = None
    embedding_service = None
    ranking_config = None

    # Embedding provenance for RetrievalMetadata (agent_memory = all-MiniLM-L6-v2, 384-dim).
    _EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    _EMBEDDING_DIM = 384

    # Contract-enum guards for MemoryItem payload normalization.
    _MEMORY_TYPES = frozenset(
        {"trade_decision", "analysis", "mistake", "insight", "task_summary", "other"}
    )
    _MEMORY_AREAS = frozenset({"main", "fragments", "solutions"})

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
            # E-HIGH1 (Phase 137) self-acquire: obtain the agent_memory backend from Memory
            # at call time (mirror tools/search_knowledge.py:106-119). The backend embeds
            # the query with the correct model and applies the mandatory project + optional
            # area filter internally — the class-attr qdrant_client/embedding_service the
            # runtime never injected are gone.
            from plugins._memory.helpers.memory import Memory, _QdrantContext

            db = await Memory.get(self.agent)  # stamps db.context_id = agent.context.id (135-06)
            backend = getattr(db, "backend", None)
            ctx = _QdrantContext(
                db.memory_subdir, context_id=getattr(db, "context_id", None)
            )

            raw_hits = []
            if backend is not None:
                raw_hits = await backend.search(
                    query=request.query,
                    top_k=request.top_k,
                    context=ctx,
                    area=request.area,
                ) or []

            results = [self._to_memory_item(r, request.project_id) for r in raw_hits]

            # Build RetrievalMetadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            metadata = {
                "query_hash": query_hash,
                "project_id": request.project_id,
                "collections": ["agent_memory"],
                "total_hits": len(raw_hits),
                "result_count": len(results),
                "latency_ms": latency_ms,
                "embedding_model": self._EMBEDDING_MODEL,
                "embedding_dimension": self._EMBEDDING_DIM,
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
            # Graceful degradation — leak-safe: the exception CLASS only goes to the log
            # (never str(e)/host:port), and empty results are returned.
            logger.error(json.dumps({
                "event": "qdrant_search",
                "collection": "agent_memory",
                "status": "error",
                "error_type": type(e).__name__,
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
                    "embedding_model": self._EMBEDDING_MODEL,
                    "embedding_dimension": self._EMBEDDING_DIM,
                }
            }

    def _to_memory_item(self, r: dict, project_id: str) -> dict:
        """Normalize an agent_memory backend hit into a MemoryItem-shaped dict.

        QdrantBackend.search returns ``{"id", "score", **payload}``. agent_memory payloads
        carry summary/area/project/timestamp/task_id but NOT the required ``type`` enum, so
        we default it (and coerce area/task_id) to satisfy the SearchMemoryResponse contract.
        """
        area = r.get("area")
        if area not in self._MEMORY_AREAS:
            area = None
        mem_type = r.get("type")
        if mem_type not in self._MEMORY_TYPES:
            mem_type = "other"
        task_id = r.get("task_id")
        if task_id in (None, "None", ""):
            task_id = None
        return {
            "id": str(r.get("id") or r.get("original_id") or ""),
            "summary": r.get("summary") or "",
            "area": area,
            "project": r.get("project") or project_id,
            "task_id": task_id,
            "type": mem_type,
            "timestamp": r.get("timestamp") or (datetime.utcnow().isoformat() + "Z"),
            "score": r.get("score"),
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
