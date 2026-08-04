"""Qdrant-based memory backend implementation.

Dual-model architecture:
- agent_memory: 384-dim (all-MiniLM-L6-v2) for chat memories
- knowledge_base: 768-dim (bge-base-en-v1.5) for books/papers/docs
- trading_context: 768-dim (bge-base-en-v1.5) for strategy rules
"""

import asyncio
import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    PointIdsList,
    FilterSelector,
)

logger = logging.getLogger(__name__)


class QdrantBackend:
    """Qdrant implementation of MemoryBackend Protocol.

    Features:
    - Project-scoped isolation (mandatory filter on all searches)
    - Per-collection vector dimensions (384 for agent_memory, 768 for knowledge/trading)
    - Cosine distance for similarity
    - Graceful degradation when Qdrant unavailable
    """

    def __init__(
        self,
        client: QdrantClient,
        embedding_service: Any,  # EmbeddingService for text-to-vector conversion
        collection_name: str = "agent_memory",
        vector_size: int = 384,
        vector_name: str | None = None,
        project_scoped: bool = True,
    ):
        """Initialize QdrantBackend with client and embedding service.

        Args:
            client: QdrantClient instance
            embedding_service: EmbeddingService for text-to-vector conversion
            collection_name: Collection to use
            vector_size: Vector dimensions (384 for agent_memory, 768 for knowledge/trading)
            vector_name: Named vector to query with (``using=``). None → default/unnamed
                vector (agent_memory, knowledge_base). Set e.g. "general_embedding" for
                multi-named-vector collections like knowledge_base_v2.
            project_scoped: When True (default) every search is filtered to the caller's
                project_id. Set False for globally-shared corpora (books/papers) whose
                points carry no "project" field — otherwise the filter matches nothing.
        """
        self.client = client
        self.embedding_service = embedding_service
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.vector_name = vector_name
        self.project_scoped = project_scoped

        # Only auto-create single-vector collections we own. Named-vector collections
        # (vector_name set, e.g. knowledge_base_v2) are provisioned/owned externally
        # (VM101 ingest) — never create them here (would make a wrong-schema collection).
        if self.vector_name is None:
            self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create this backend's Qdrant collection if it doesn't exist.

        Uses self.vector_size for the vector dimension.
        Idempotent: Safe to call multiple times.
        """
        try:
            if not self.client.collection_exists(collection_name=self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
                self._log_structured(
                    "info",
                    "collection_created",
                    {"collection": self.collection_name, "vector_size": self.vector_size, "distance": "cosine"},
                )
            else:
                self._log_structured(
                    "debug",
                    "collection_exists",
                    {"collection": self.collection_name},
                )
        except Exception as e:
            self._log_structured(
                "error",
                "collection_creation_failed",
                {"collection": self.collection_name, "error": str(e)},
            )

    async def add(self, items: list[dict], context) -> None:
        """Add memory items to Qdrant collection.

        Embeds summaries via EmbeddingService and upserts to collection
        with schema_version and project metadata.

        Args:
            items: List of memory items (dict with id, summary, area, project, etc.)
            context: AgentContext with project_id

        Returns:
            None (logs errors instead of raising)
        """
        if not items:
            return

        try:
            # Extract summaries for embedding
            summaries = [item.get("summary", "") for item in items]

            # Get project_id from context
            project_id = getattr(context, "project_id", None) or getattr(
                context, "memory_subdir", "default"
            )

            # Embed summaries
            embed_response = await self.embedding_service.embed(
                texts=summaries,
                project_id=project_id,
                model="BAAI/bge-base-en-v1.5",
                normalize=True,
            )

            # Build points for upsert
            points = []
            for idx, item in enumerate(items):
                vector = embed_response.embeddings[idx]

                # Build payload with schema_version
                payload = {
                    "summary": item.get("summary", ""),
                    "area": item.get("area"),
                    "project": item.get("project", project_id),
                    "schema_version": "v1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "task_id": getattr(context, "task_id", None),
                }

                # Include additional fields from item
                for key in ["type", "confidence", "metadata", "content"]:
                    if key in item:
                        payload[key] = item[key]

                # Qdrant requires UUID or unsigned int IDs
                point_id = self._to_uuid(item["id"])
                payload["original_id"] = item["id"]  # preserve original for lookups

                points.append(
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                )

            # Upsert to collection (offloaded off the event loop — A1/D-03)
            await asyncio.to_thread(
                lambda: self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
            )

            self._log_structured(
                "info",
                "memories_added",
                {
                    "collection": self.collection_name,
                    "count": len(points),
                    "project": project_id,
                },
            )

        except Exception as e:
            self._log_structured(
                "error",
                "add_failed",
                {
                    "collection": self.collection_name,
                    "error": str(e),
                    "item_count": len(items),
                },
            )

    async def search(
        self,
        query: str,
        top_k: int,
        context,
        area: str | None = None,
    ) -> list[dict]:
        """Search for similar memories with mandatory project filter.

        Args:
            query: Search query text
            top_k: Maximum number of results
            context: AgentContext with project_id
            area: Optional area filter ("main", "fragments", "solutions")

        Returns:
            List of matching items (dict format)

        Note:
            Project filter is ALWAYS applied (callers cannot bypass)
            Returns empty list if Qdrant unavailable (graceful degradation)
        """
        try:
            # Get project_id from context
            project_id = getattr(context, "project_id", None) or getattr(
                context, "memory_subdir", "default"
            )

            # Embed query
            embed_response = await self.embedding_service.embed(
                texts=[query],
                project_id=project_id,
                model="BAAI/bge-base-en-v1.5",
                normalize=True,
            )
            query_vector = embed_response.embeddings[0]

            # Build project filter (mandatory for project-scoped collections; skipped
            # for globally-shared corpora whose points carry no "project" field).
            filter_conditions = []
            if self.project_scoped:
                filter_conditions.append(
                    FieldCondition(
                        key="project",
                        match=MatchValue(value=project_id),
                    )
                )

            # Add optional area filter
            if area is not None:
                filter_conditions.append(
                    FieldCondition(
                        key="area",
                        match=MatchValue(value=area),
                    )
                )

            query_filter = Filter(must=filter_conditions) if filter_conditions else None

            # Search using query_points (qdrant-client >= 1.12). For named-vector
            # collections, `using` selects which vector space to search.
            qp_kwargs = {
                "collection_name": self.collection_name,
                "query": query_vector,
                "limit": top_k,
            }
            if query_filter is not None:
                qp_kwargs["query_filter"] = query_filter
            if self.vector_name is not None:
                qp_kwargs["using"] = self.vector_name
            # Offloaded off the event loop — A1/D-03 (network vector I/O)
            search_response = await asyncio.to_thread(lambda: self.client.query_points(**qp_kwargs))

            # Convert to dict format
            results = []
            for hit in search_response.points:
                # Use original_id from payload if available, else UUID
                original_id = hit.payload.get("original_id", str(hit.id))
                result = {
                    "id": original_id,
                    "score": hit.score,
                    **hit.payload,
                }
                results.append(result)

            self._log_structured(
                "info",
                "search_completed",
                {
                    "collection": self.collection_name,
                    "project": project_id,
                    "area": area,
                    "results": len(results),
                },
            )

            return results

        except Exception as e:
            self._log_structured(
                "warning",
                "search_failed_graceful_degradation",
                {
                    "collection": self.collection_name,
                    "error": str(e),
                },
            )
            return []

    async def delete(self, ids: list[str], context) -> None:
        """Delete memory items by ID within project scope.

        Args:
            ids: List of item IDs to delete
            context: AgentContext with project_id

        Returns:
            None
        """
        if not ids:
            return

        try:
            # Get project_id for logging (actual deletion by ID)
            project_id = getattr(context, "project_id", None) or getattr(
                context, "memory_subdir", "default"
            )

            # Convert string IDs to UUIDs (same deterministic hash as add)
            uuid_ids = [self._to_uuid(id_str) for id_str in ids]

            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=uuid_ids),
            )

            self._log_structured(
                "info",
                "memories_deleted",
                {
                    "collection": self.collection_name,
                    "project": project_id,
                    "count": len(ids),
                },
            )

        except Exception as e:
            self._log_structured(
                "error",
                "delete_failed",
                {
                    "collection": self.collection_name,
                    "error": str(e),
                },
            )

    async def clear(self, context) -> None:
        """Clear all memories for a project.

        WARNING: DANGEROUS operation - removes ALL points for project.

        Args:
            context: AgentContext with project_id

        Returns:
            None
        """
        try:
            # Get project_id from context
            project_id = getattr(context, "project_id", None) or getattr(
                context, "memory_subdir", "default"
            )

            # Delete all points with project filter
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="project",
                                match=MatchValue(value=project_id),
                            )
                        ]
                    )
                ),
            )

            self._log_structured(
                "warning",
                "project_memories_cleared",
                {
                    "collection": self.collection_name,
                    "project": project_id,
                },
            )

        except Exception as e:
            self._log_structured(
                "error",
                "clear_failed",
                {
                    "collection": self.collection_name,
                    "error": str(e),
                },
            )

    @staticmethod
    def _to_uuid(id_str: str) -> str:
        """Convert an arbitrary string ID to a deterministic UUID v5.

        Qdrant requires UUIDs or unsigned ints for point IDs.
        Agent Zero generates random alphanumeric strings (e.g., 'YZv9zp3X9V').
        This converts them deterministically so the same string always maps
        to the same UUID (needed for delete-by-ID to work).
        """
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, id_str))

    def _log_structured(self, level: str, event: str, data: dict) -> None:
        """Emit structured JSON log with ISO 8601 Z suffix.

        Args:
            level: Log level (info, warning, error, debug)
            event: Event name
            data: Event data
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": level.upper(),
            "event": event,
            "component": "qdrant_backend",
            **data,
        }

        log_message = json.dumps(log_entry)

        if level == "debug":
            logger.debug(log_message)
        elif level == "info":
            logger.info(log_message)
        elif level == "warning":
            logger.warning(log_message)
        elif level == "error":
            logger.error(log_message)
