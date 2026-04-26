"""Integration tests for knowledge_base vs agent_memory collection separation.

Verifies that:
- KnowledgeIngestionService writes ONLY to knowledge_base
- QdrantBackend.add writes ONLY to agent_memory
- SearchKnowledgeTool queries ONLY knowledge_base
- SearchMemoryTool queries ONLY agent_memory
- No cross-collection writes occur
"""

import pytest
from unittest.mock import Mock, AsyncMock, call, patch


@pytest.mark.integration
class TestCollectionSeparation:
    """Test that knowledge and memory never cross-contaminate collections."""

    def test_knowledge_ingestion_writes_only_to_knowledge_base(self):
        """KnowledgeIngestionService should write ONLY to knowledge_base collection."""
        # Mock dependencies
        mock_qdrant_client = Mock()
        mock_embedding_service = Mock()
        # Mock embed response with embeddings attribute
        mock_response = Mock()
        mock_response.embeddings = [[0.1] * 768]
        mock_embedding_service.embed = Mock(return_value=mock_response)

        # Import here to avoid circular dependencies
        import sys
        from pathlib import Path
        vm101_backend_path = Path("/Volumes/ HardDrive/FinGPT/VM101/backend")
        if str(vm101_backend_path) not in sys.path:
            sys.path.insert(0, str(vm101_backend_path))

        # Import KnowledgeIngestionService from VM101
        try:
            from knowledge.ingestion_service import KnowledgeIngestionService
        except ImportError:
            pytest.skip("KnowledgeIngestionService not available (VM101 backend not in path)")

        service = KnowledgeIngestionService(
            qdrant_client=mock_qdrant_client,
            embedding_service=mock_embedding_service,
        )

        # Ingest a test document
        service.ingest_document(
            document_id="test_doc",
            text="This is a test document with enough content to pass validation and chunking requirements.",
            metadata={"title": "Test Document", "source_type": "manual"},
            project="test_project",
        )

        # Verify upsert was called with knowledge_base collection
        mock_qdrant_client.upsert.assert_called_once()
        upsert_call = mock_qdrant_client.upsert.call_args

        assert upsert_call.kwargs["collection_name"] == "knowledge_base"
        assert upsert_call.kwargs["collection_name"] != "agent_memory"

    @pytest.mark.asyncio
    async def test_qdrant_backend_writes_only_to_agent_memory(self):
        """QdrantBackend.add should write ONLY to agent_memory collection."""
        # Mock dependencies
        mock_qdrant_client = Mock()
        mock_embedding_service = AsyncMock()
        mock_embedding_service.embed = AsyncMock(return_value=Mock(
            embeddings=[[0.1] * 768],
            dimension=768,
        ))

        # Import QdrantBackend
        import sys
        from pathlib import Path
        vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
        if str(vm107_path) not in sys.path:
            sys.path.insert(0, str(vm107_path))

        from plugins._memory.backend.qdrant_backend import QdrantBackend

        backend = QdrantBackend(
            client=mock_qdrant_client,
            embedding_service=mock_embedding_service,
            collection_name="agent_memory",
        )

        # Mock context
        mock_context = Mock()
        mock_context.project_id = "test_project"
        mock_context.task_id = "test_task"

        # Add memory items
        items = [
            {
                "id": "mem_001",
                "summary": "Test memory item with enough content to be valid",
                "area": "main",
                "project": "test_project",
            }
        ]

        await backend.add(items, mock_context)

        # Verify upsert was called with agent_memory collection
        mock_qdrant_client.upsert.assert_called_once()
        upsert_call = mock_qdrant_client.upsert.call_args

        assert upsert_call.kwargs["collection_name"] == "agent_memory"
        assert upsert_call.kwargs["collection_name"] != "knowledge_base"

    def test_search_knowledge_tool_queries_only_knowledge_base(self):
        """SearchKnowledgeTool should query ONLY knowledge_base collection.

        Verifies hardcoded collection name by reading source file directly.
        """
        from pathlib import Path

        tool_file = Path("/Volumes/ HardDrive/FinGPT/VM107/tools/qdrant/search_knowledge.py")

        if not tool_file.exists():
            pytest.skip("SearchKnowledgeTool source not found")

        source = tool_file.read_text()

        # Verify "knowledge_base" appears in the search call
        assert 'collection_name="knowledge_base"' in source
        assert 'collection_name="agent_memory"' not in source

    def test_search_memory_tool_queries_only_agent_memory(self):
        """SearchMemoryTool should query ONLY agent_memory collection.

        Verifies hardcoded collection name by reading source file directly.
        """
        from pathlib import Path

        tool_file = Path("/Volumes/ HardDrive/FinGPT/VM107/tools/qdrant/search_memory.py")

        if not tool_file.exists():
            pytest.skip("SearchMemoryTool source not found")

        source = tool_file.read_text()

        # Verify "agent_memory" appears in the search call
        assert 'collection_name="agent_memory"' in source
        assert 'collection_name="knowledge_base"' not in source

    @pytest.mark.asyncio
    async def test_no_cross_collection_writes(self):
        """Verify that knowledge and memory systems never write to each other's collections."""
        # This is a meta-test that verifies the separation by checking all write paths

        # Mock a Qdrant client that tracks all upsert calls
        write_tracker = []

        def track_upsert(collection_name, **kwargs):
            write_tracker.append(collection_name)

        mock_qdrant_client = Mock()
        mock_qdrant_client.upsert = Mock(side_effect=track_upsert)

        mock_embedding_service = Mock()
        # Mock embed response with embeddings attribute
        mock_response = Mock()
        mock_response.embeddings = [[0.1] * 768]
        mock_embedding_service.embed = Mock(return_value=mock_response)

        # Test knowledge ingestion
        import sys
        from pathlib import Path
        vm101_backend_path = Path("/Volumes/ HardDrive/FinGPT/VM101/backend")
        if str(vm101_backend_path) not in sys.path:
            sys.path.insert(0, str(vm101_backend_path))

        try:
            from knowledge.ingestion_service import KnowledgeIngestionService

            knowledge_service = KnowledgeIngestionService(
                qdrant_client=mock_qdrant_client,
                embedding_service=mock_embedding_service,
            )

            knowledge_service.ingest_document(
                document_id="test_doc",
                text="Test knowledge document with sufficient content for validation and chunking requirements.",
                metadata={"title": "Test", "source_type": "manual"},
                project="test_project",
            )

        except ImportError:
            pytest.skip("KnowledgeIngestionService not available")

        # Test memory backend
        vm107_path = Path("/Volumes/ HardDrive/FinGPT/VM107")
        if str(vm107_path) not in sys.path:
            sys.path.insert(0, str(vm107_path))

        from plugins._memory.backend.qdrant_backend import QdrantBackend

        mock_embedding_service.embed = AsyncMock(return_value=Mock(
            embeddings=[[0.1] * 768],
        ))

        memory_backend = QdrantBackend(
            client=mock_qdrant_client,
            embedding_service=mock_embedding_service,
            collection_name="agent_memory",
        )

        mock_context = Mock()
        mock_context.project_id = "test_project"
        mock_context.task_id = "test_task"

        await memory_backend.add(
            [
                {
                    "id": "mem_001",
                    "summary": "Test memory item with sufficient content for validation.",
                    "area": "main",
                }
            ],
            mock_context,
        )

        # Verify no cross-contamination
        assert len(write_tracker) == 2
        assert write_tracker[0] == "knowledge_base"
        assert write_tracker[1] == "agent_memory"
        assert "knowledge_base" != "agent_memory"  # Collections are distinct
