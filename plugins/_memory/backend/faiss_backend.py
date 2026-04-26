"""FAISS-based memory backend implementation (backward compatibility wrapper)."""


class FaissBackend:
    """FAISS implementation of MemoryBackend Protocol.

    Wraps existing MyFaiss class to preserve backward compatibility
    while conforming to the new MemoryBackend Protocol.

    Note:
        This is a thin wrapper - all existing FAISS logic is preserved.
        The Memory class will continue to use MyFaiss directly when
        backend="faiss" is configured.
    """

    def __init__(self, agent):
        """Initialize FaissBackend.

        Args:
            agent: Agent instance (required for MyFaiss initialization)
        """
        self.agent = agent
        self.index = None  # Will be set by Memory class

    async def add(self, items: list[dict], context) -> None:
        """Add memory items (delegates to MyFaiss.insert_text).

        Args:
            items: List of memory items
            context: AgentContext

        Returns:
            None
        """
        # Existing FAISS logic will be called via Memory class
        # This is a placeholder for Protocol compliance
        pass

    async def search(
        self,
        query: str,
        top_k: int,
        context,
        area: str | None = None,
    ) -> list[dict]:
        """Search for similar memories (delegates to MyFaiss.search_similarity_threshold).

        Args:
            query: Search query text
            top_k: Maximum number of results
            context: AgentContext
            area: Optional area filter

        Returns:
            List of matching items
        """
        # Existing FAISS logic will be called via Memory class
        # This is a placeholder for Protocol compliance
        return []

    async def delete(self, ids: list[str], context) -> None:
        """Delete memory items by ID (delegates to MyFaiss.delete_documents_by_ids).

        Args:
            ids: List of item IDs to delete
            context: AgentContext

        Returns:
            None
        """
        # Existing FAISS logic will be called via Memory class
        # This is a placeholder for Protocol compliance
        pass

    async def clear(self, context) -> None:
        """Clear all memories for a project.

        Args:
            context: AgentContext

        Returns:
            None
        """
        # Existing FAISS logic will be called via Memory class
        # This is a placeholder for Protocol compliance
        pass
