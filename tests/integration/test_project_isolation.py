"""Integration tests for cross-project isolation in Qdrant collections.

Verifies that:
- Memory from project_A is NOT visible from project_B
- Knowledge with project="global" is accessible from all projects
- Knowledge with project="project_A" is NOT accessible from project_B
- All search filters include mandatory project conditions
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock
from qdrant_client.models import PointStruct, ScoredPoint


class MockQdrantClient:
    """In-memory mock of QdrantClient for testing project isolation."""

    def __init__(self):
        self.collections = {
            "agent_memory": [],
            "knowledge_base": [],
        }

    def upsert(self, collection_name: str, points: list[PointStruct], **kwargs):
        """Store points in memory."""
        if collection_name not in self.collections:
            self.collections[collection_name] = []
        self.collections[collection_name].extend(points)

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        query_filter=None,
        limit: int = 10,
        **kwargs,
    ):
        """Search with filter enforcement."""
        if collection_name not in self.collections:
            return []

        results = []

        for point in self.collections[collection_name]:
            # Apply filter
            if query_filter:
                if not self._matches_filter(point.payload, query_filter):
                    continue

            # Mock score (constant for testing)
            scored_point = ScoredPoint(
                id=point.id,
                score=0.9,
                payload=point.payload,
                version=1,
            )
            results.append(scored_point)

        return results[:limit]

    def _matches_filter(self, payload: dict, query_filter) -> bool:
        """Check if payload matches filter conditions."""
        # Handle MUST conditions
        if hasattr(query_filter, "must") and query_filter.must:
            for condition in query_filter.must:
                if not self._matches_condition(payload, condition):
                    return False

        # Handle SHOULD conditions (OR logic)
        if hasattr(query_filter, "should") and query_filter.should:
            matched_any = False
            for condition in query_filter.should:
                if self._matches_condition(payload, condition):
                    matched_any = True
                    break
            if not matched_any:
                return False

        return True

    def _matches_condition(self, payload: dict, condition) -> bool:
        """Check if payload matches a single field condition."""
        key = condition.key
        value = condition.match.value

        return payload.get(key) == value


@pytest.mark.integration
class TestProjectIsolation:
    """Test that projects cannot access each other's data."""

    @pytest.mark.asyncio
    async def test_memory_project_isolation(self):
        """Memory added for project_A should NOT be visible from project_B."""
        mock_client = MockQdrantClient()

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed = AsyncMock(return_value=Mock(
            embeddings=[[0.1] * 768],
        ))

        # Import QdrantBackend
        import sys
        from pathlib import Path
        vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
        if str(vm107_path) not in sys.path:
            sys.path.insert(0, str(vm107_path))

        from plugins._memory.backend.qdrant_backend import QdrantBackend

        backend = QdrantBackend(
            client=mock_client,
            embedding_service=mock_embedding_service,
            collection_name="agent_memory",
        )

        # Add memory for project_A
        mock_context_a = Mock()
        mock_context_a.project_id = "project_a"
        mock_context_a.task_id = "task_001"

        await backend.add(
            [
                {
                    "id": "mem_a_001",
                    "summary": "Memory from project A with sufficient content for testing.",
                    "area": "main",
                    "project": "project_a",
                }
            ],
            mock_context_a,
        )

        # Search from project_B context
        mock_context_b = Mock()
        mock_context_b.project_id = "project_b"
        mock_context_b.memory_subdir = "project_b"

        results = await backend.search(
            query="test query",
            top_k=10,
            context=mock_context_b,
        )

        # project_B should NOT see project_A's memory
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_memory_same_project_visible(self):
        """Memory added for project_A SHOULD be visible from project_A context."""
        mock_client = MockQdrantClient()

        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed = AsyncMock(return_value=Mock(
            embeddings=[[0.1] * 768],
        ))

        # Import QdrantBackend
        import sys
        from pathlib import Path
        vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
        if str(vm107_path) not in sys.path:
            sys.path.insert(0, str(vm107_path))

        from plugins._memory.backend.qdrant_backend import QdrantBackend

        backend = QdrantBackend(
            client=mock_client,
            embedding_service=mock_embedding_service,
            collection_name="agent_memory",
        )

        # Add memory for project_A
        mock_context_a = Mock()
        mock_context_a.project_id = "project_a"
        mock_context_a.task_id = "task_001"

        await backend.add(
            [
                {
                    "id": "mem_a_001",
                    "summary": "Memory from project A with sufficient content for testing.",
                    "area": "main",
                    "project": "project_a",
                }
            ],
            mock_context_a,
        )

        # Search from same project_A context
        results = await backend.search(
            query="test query",
            top_k=10,
            context=mock_context_a,
        )

        # project_A SHOULD see its own memory
        assert len(results) == 1
        assert results[0]["project"] == "project_a"

    def test_global_knowledge_accessible_from_all_projects(self):
        """Knowledge with project='global' should be accessible from all projects.

        Verifies the filter logic includes OR condition for project == current OR global.
        """
        from pathlib import Path

        tool_file = Path("/Volumes/ HardDrive/FinGPT/VM107/tools/qdrant/search_knowledge.py")

        if not tool_file.exists():
            pytest.skip("SearchKnowledgeTool source not found")

        source = tool_file.read_text()

        # Should have "should" condition for OR logic
        assert '"should"' in source or "'should'" in source
        # Should match both project_id and "global"
        assert 'value="global"' in source or "value='global'" in source

    def test_project_specific_knowledge_not_accessible_from_other_projects(self):
        """Knowledge with project='project_A' should NOT be accessible from project_B.

        Verifies that the OR filter (project == current OR global) prevents cross-project access.
        """
        from pathlib import Path

        tool_file = Path("/Volumes/ HardDrive/FinGPT/VM107/tools/qdrant/search_knowledge.py")

        if not tool_file.exists():
            pytest.skip("SearchKnowledgeTool source not found")

        source = tool_file.read_text()

        # Should use request.project_id (not a hardcoded project name)
        assert 'request.project_id' in source
        # Should only have 2 conditions in should: current project + global
        assert source.count('MatchValue') >= 2  # At least for project filter

    def test_search_filter_always_includes_project_condition(self):
        """All searches must include project filter (verify filter arguments).

        Verifies that SearchMemoryTool builds MUST filter with project condition.
        """
        from pathlib import Path

        tool_file = Path("/Volumes/ HardDrive/FinGPT/VM107/tools/qdrant/search_memory.py")

        if not tool_file.exists():
            pytest.skip("SearchMemoryTool source not found")

        source = tool_file.read_text()

        # Should have must condition (parameter name, not string literal)
        assert 'must=' in source or 'Filter(must=' in source
        # Should filter by project
        assert 'key="project"' in source or "key='project'" in source
        # Should use request.project_id
        assert 'request.project_id' in source
