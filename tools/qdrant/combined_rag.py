"""
CombinedRAGTool for merged memory + knowledge retrieval.

Searches both agent_memory and knowledge_base_v2 collections,
merges results into token-bounded combined context for LLM prompts.
Uses multi-vector search with QueryRouter for knowledge retrieval.
"""
import hashlib
import json
import logging
import time
from datetime import datetime

from fingpt_core.contracts import (
    CombinedRAGRequest,
    CombinedRAGResponse,
    KnowledgeItem,
    MemoryItem,
    RetrievalMetadata,
)
from helpers.tool import Response
from tools.graph.graph_search_tool import GraphSearchRequest
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

    E-HIGH1 (Phase 137): the tool SELF-ACQUIRES its per-collection backends at call
    time via ``Memory.get(self.agent)`` (mirror the P4 tools/search_knowledge.py
    pattern) — it no longer relies on the qdrant_client/embedding_service/ranking_config
    class attributes the runtime never injected (the activation gap that made every
    live call degrade to "No relevant context found."). agent_memory (384-dim MiniLM)
    and knowledge_base_v2 (768-dim BGE, named vector) need DIFFERENT embedders, so each
    search is routed through its OWN backend (which self-embeds correctly) rather than a
    single shared query vector. The class attributes below are retained ONLY for the
    legacy DI-mock harness (tests/tools/test_combined_rag.py); they are NOT read on the
    happy path.
    """

    # Legacy DI class attributes — retained for the old DI-mock test harness only.
    # NOT used on the self-acquire happy path (E-HIGH1, Phase 137).
    qdrant_client = None
    embedding_service = None
    ranking_config = None
    neo4j_driver = None  # For graph expansion (Phase 40.2)

    # Embedding provenance surfaced in RetrievalMetadata. knowledge_base_v2 is the
    # dominant (global) corpus and drives the reported model/dimension.
    _EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
    _EMBEDDING_DIM = 768

    # Contract-enum guards for payload normalization (MemoryItem / KnowledgeItem).
    _MEMORY_TYPES = frozenset(
        {"trade_decision", "analysis", "mistake", "insight", "task_summary", "other"}
    )
    _MEMORY_AREAS = frozenset({"main", "fragments", "solutions"})
    _KNOWLEDGE_SOURCE_TYPES = frozenset(
        {"book", "paper", "article", "markdown", "internal_doc", "transcript", "other"}
    )

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
            # E-HIGH1 (Phase 137) self-acquire: obtain the per-collection backends from
            # Memory at call time (mirror tools/search_knowledge.py:106-119). Each backend
            # self-embeds with the CORRECT model for its collection (agent_memory=384-dim
            # MiniLM, knowledge_base_v2=768-dim BGE named-vector) — a single shared query
            # vector could not serve both, which was the original activation gap.
            from plugins._memory.helpers.memory import Memory, _QdrantContext

            db = await Memory.get(self.agent)  # stamps db.context_id = agent.context.id (135-06)
            ctx = _QdrantContext(
                db.memory_subdir, context_id=getattr(db, "context_id", None)
            )
            memory_backend = getattr(db, "backend", None)        # agent_memory collection
            knowledge_backend = db._get_knowledge_v2_backend()   # knowledge_base_v2 (global)

            # Search agent_memory (backend applies the mandatory project filter + embeds).
            memory_results: list[dict] = []
            if memory_backend is not None:
                raw_memory = await memory_backend.search(
                    query=request.query,
                    top_k=request.memory_top_k,
                    context=ctx,
                    area=None,
                ) or []
                memory_results = [
                    self._to_memory_item(r, request.project_id) for r in raw_memory
                ]

            # Search knowledge_base_v2 (global corpus, BGE general_embedding named vector).
            knowledge_results: list[dict] = []
            if knowledge_backend is not None:
                raw_knowledge = await knowledge_backend.search(
                    query=request.query,
                    top_k=request.knowledge_top_k,
                    context=ctx,
                    area=None,
                ) or []
                knowledge_results = [
                    self._to_knowledge_item(r, request.project_id) for r in raw_knowledge
                ]

            # Graph expansion (if relationship query detected; neo4j_driver None -> [])
            graph_results = await self._expand_graph(request.query)

            # Build combined context
            combined_context = self._build_combined_context(
                memory_results,
                knowledge_results,
                graph_results,
                request.max_context_tokens
            )

            # Build RetrievalMetadata
            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            metadata = {
                "query_hash": query_hash,
                "project_id": request.project_id,
                "collections": ["agent_memory", "knowledge_base_v2"],
                "total_hits": len(memory_results) + len(knowledge_results),
                "result_count": len(memory_results) + len(knowledge_results),
                "latency_ms": latency_ms,
                "embedding_model": self._EMBEDDING_MODEL,
                "embedding_dimension": self._EMBEDDING_DIM,
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
            # Graceful degradation — the REAL-outage path, not the default. Leak-safe:
            # the exception CLASS only goes to the log; the RESPONSE carries a generic
            # empty context (never str(e) / host:port / IP), mirroring the P4 discipline.
            logger.error(json.dumps({
                "event": "combined_rag_search",
                "status": "error",
                "error_type": type(e).__name__,
                "timestamp": timestamp
            }))

            query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "memory_results": [],
                "knowledge_results": [],
                "graph_results": [],  # Graph expansion also empty on error
                "combined_context": "No relevant context found.",
                "metadata": {
                    "query_hash": query_hash,
                    "project_id": request.project_id,
                    "collections": ["agent_memory", "knowledge_base_v2", "neo4j_graph"],
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
        we default it (and coerce area/task_id) to satisfy the CombinedRAGResponse contract.
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

    def _to_knowledge_item(self, r: dict, project_id: str) -> dict:
        """Normalize a knowledge_base_v2 backend hit into a KnowledgeItem-shaped dict.

        knowledge_base_v2 payloads carry text/book_title/category/document_id but NOT the
        required ``source_type``/``project`` fields (it is a global corpus), so we default
        them to satisfy the CombinedRAGResponse contract.
        """
        source_type = r.get("source_type")
        if source_type not in self._KNOWLEDGE_SOURCE_TYPES:
            source_type = "other"
        doc_id = r.get("document_id")
        return {
            "text": r.get("text") or "",
            "title": r.get("title") or r.get("book_title"),
            "topic": r.get("topic") or r.get("category"),
            "source_type": source_type,
            "project": r.get("project") or "global",
            "document_id": str(doc_id) if doc_id is not None else None,
            "score": r.get("score"),
        }

    async def _expand_graph(self, query: str) -> list[dict]:
        """
        Expand query with Neo4j graph context if relationship query detected.

        Uses QueryRouter to detect relationship keywords, extracts concepts,
        and runs GraphSearchTool's find_related template for co-occurring entities.

        Graceful degradation:
        - neo4j_driver is None -> returns empty list
        - Neo4j connection fails -> returns empty list
        - No concepts extracted -> returns empty list
        - Query not relationship-oriented -> returns empty list

        Args:
            query: User query string

        Returns:
            List of graph result dicts (empty if no expansion needed)
        """
        # Check if graph expansion should be triggered
        if not self.query_router.should_expand_graph(query):
            return []

        # Graceful degradation: neo4j_driver is None
        if self.neo4j_driver is None:
            return []

        # Extract concepts from query
        concepts = self.query_router.extract_concepts_from_query(query)
        if not concepts:
            return []

        # Query Neo4j for each concept using find_related template
        all_graph_results = []

        for concept in concepts:
            try:
                # Build GraphSearchRequest
                request = GraphSearchRequest(
                    template="find_related",
                    concept_name=concept,
                    top_k=5  # Smaller top_k for graph results (not overwhelming)
                )

                # Execute Cypher query via Neo4j driver
                cypher_query = """
                    MATCH (a)-[:MENTIONS]-(chunk:Chunk)-[:MENTIONS]-(b)
                    WHERE a.name = $concept_name
                      AND a <> b
                    RETURN DISTINCT b.name AS related_entity,
                           labels(b) AS entity_type,
                           count(chunk) AS co_occurrence_count
                    ORDER BY co_occurrence_count DESC
                    LIMIT $top_k
                """

                params = {
                    "concept_name": request.concept_name,
                    "top_k": request.top_k
                }

                with self.neo4j_driver.session() as session:
                    result = session.run(cypher_query, **params)
                    records = [dict(record) for record in result]

                # Add source concept to each result
                for record in records:
                    record["source_concept"] = concept
                    all_graph_results.append(record)

            except Exception as e:
                # Graceful degradation: log error, continue to next concept
                logger.warning(json.dumps({
                    "event": "graph_expansion",
                    "status": "error",
                    "concept": concept,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }))
                continue

        return all_graph_results

    def _build_combined_context(
        self,
        memory_results: list[dict],
        knowledge_results: list[dict],
        graph_results: list[dict],
        max_context_tokens: int
    ) -> str:
        """
        Build combined context string within token budget.

        Context merge order (per CONTEXT.md locked decision):
        1. VALIDATED RELATIONSHIPS (graph results - facts from Neo4j)
        2. AGENT MEMORY (recent task-specific context)
        3. SUPPORTING KNOWLEDGE (Qdrant semantic chunks)

        Context trimmed by dropping lowest-scored items until within token budget.

        Args:
            memory_results: Memory search results
            knowledge_results: Knowledge search results
            graph_results: Graph expansion results (relationship data)
            max_context_tokens: Maximum tokens for combined context

        Returns:
            Combined context string
        """
        if not memory_results and not knowledge_results and not graph_results:
            return "No relevant context found."

        # Build sections (graph first, then memory, then knowledge)
        sections = []

        if graph_results:
            graph_lines = ["=== VALIDATED RELATIONSHIPS ==="]
            for idx, item in enumerate(graph_results, 1):
                source = item.get("source_concept", "Unknown")
                related = item.get("related_entity", "Unknown")
                co_occur = item.get("co_occurrence_count", 0)
                entity_type = item.get("entity_type", [])
                type_str = entity_type[0] if entity_type else "Unknown"
                graph_lines.append(
                    f"[{idx}] {source} is related to {related} "
                    f"(type: {type_str}, co-occurrences: {co_occur})"
                )
            sections.append("\n".join(graph_lines))

        if memory_results:
            memory_lines = ["=== AGENT MEMORY ==="]
            for idx, item in enumerate(memory_results, 1):
                summary = item.get("summary", "")
                score = item.get("score", 0)
                memory_lines.append(f"[{idx}] {summary} (Score: {score:.3f})")
            sections.append("\n".join(memory_lines))

        if knowledge_results:
            knowledge_lines = ["=== SUPPORTING KNOWLEDGE ==="]
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
        # Graph results always included (they're facts, not scored by relevance)
        # Only memory and knowledge results are subject to trimming
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
                graph_results,  # Graph results always included
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
                    graph_results,  # Graph results always included
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
