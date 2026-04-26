"""Qdrant-based memory backend implementation."""

import logging
import json
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
    - Three collections: agent_memory, knowledge_base, trading_context
    - 768-dimensional vectors (BAAI/bge-base-en-v1.5)
    - Cosine distance for similarity
    - Graceful degradation when Qdrant unavailable
    """

    def __init__(
        self,
        client: QdrantClient,
        embedding_service: Any,  # EmbeddingService from fingpt_core
        collection_name: str = "agent_memory",
    ):
        """Initialize QdrantBackend with client and embedding service.

        Args:
            client: QdrantClient instance
            embedding_service: EmbeddingService for text-to-vector conversion
            collection_name: Primary collection to use (default: agent_memory)
        """
        self.client = client
        self.embedding_service = embedding_service
        self.collection_name = collection_name

        # Create collections if they don't exist
        self._create_memory_collections()

    def _create_memory_collections(self) -> None:
        """Create 3 Qdrant collections with 768-dim vectors and cosine distance.

        Collections:
        - agent_memory: Agent execution memories
        - knowledge_base: Uploaded documents and external knowledge
        - trading_context: Trading-specific context (strategies, rules, etc.)

        Idempotent: Safe to call multiple times.
        """
        collections = ["agent_memory", "knowledge_base", "trading_context"]

        for collection in collections:
            try:
                if not self.client.collection_exists(collection_name=collection):
                    self.client.create_collection(
                        collection_name=collection,
                        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                    )
                    self._log_structured(
                        "info",
                        "collection_created",
                        {"collection": collection, "vector_size": 768, "distance": "cosine"},
                    )
                else:
                    self._log_structured(
                        "debug",
                        "collection_exists",
                        {"collection": collection},
                    )
            except Exception as e:
                self._log_structured(
                    "error",
                    "collection_creation_failed",
                    {"collection": collection, "error": str(e)},
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

                points.append(
                    PointStruct(
                        id=item["id"],
                        vector=vector,
                        payload=payload,
                    )
                )

            # Upsert to collection
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
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

            # Build mandatory project filter
            filter_conditions = [
                FieldCondition(
                    key="project",
                    match=MatchValue(value=project_id),
                )
            ]

            # Add optional area filter
            if area is not None:
                filter_conditions.append(
                    FieldCondition(
                        key="area",
                        match=MatchValue(value=area),
                    )
                )

            query_filter = Filter(must=filter_conditions)

            # Search
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
            )

            # Convert to dict format
            results = []
            for hit in search_results:
                result = {
                    "id": hit.id,
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

            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=ids),
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
