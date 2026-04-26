"""MemoryBackend Protocol definition."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for memory backend implementations.

    Provides a unified interface for different storage backends (FAISS, Qdrant, etc.)
    with mandatory AgentContext for project isolation.

    All implementations must:
    - Accept AgentContext with project_id for scoping
    - Use dict-based items (not Pydantic) for backend decoupling
    - Handle graceful degradation when backend unavailable
    """

    async def add(self, items: list[dict], context) -> None:
        """Add memory items to the backend.

        Args:
            items: List of memory items (dict with id, summary, area, project, etc.)
            context: AgentContext with project_id and optional task_id

        Returns:
            None

        Raises:
            Should log errors but not raise exceptions (graceful degradation)
        """
        ...

    async def search(
        self,
        query: str,
        top_k: int,
        context,
        area: str | None = None,
    ) -> list[dict]:
        """Search for similar memories.

        Args:
            query: Search query text
            top_k: Maximum number of results to return
            context: AgentContext with project_id for scoping
            area: Optional area filter ("main", "fragments", "solutions")

        Returns:
            List of matching items (dict format)

        Note:
            - Project filter is MANDATORY (callers cannot bypass)
            - area=None searches ALL areas (default)
            - Graceful degradation: return [] if backend unavailable
        """
        ...

    async def delete(self, ids: list[str], context) -> None:
        """Delete memory items by ID.

        Args:
            ids: List of item IDs to delete
            context: AgentContext with project_id for scoping

        Returns:
            None

        Note:
            Deletion is scoped to project for safety
        """
        ...

    async def clear(self, context) -> None:
        """Clear all memories for a project.

        Args:
            context: AgentContext with project_id

        Returns:
            None

        Warning:
            DANGEROUS operation - removes ALL points for project
            Project filter prevents cross-project deletion
        """
        ...
