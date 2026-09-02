"""Test QdrantBackend implementation."""

import pytest
from unittest.mock import Mock, call
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct
from plugins._memory.backend.qdrant_backend import QdrantBackend


@pytest.mark.asyncio
async def test_collection_creation_on_init(mock_qdrant_client, mock_embedding_service):
    """QdrantBackend should create 3 collections on initialization."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    # Should check existence and create for all 3 collections
    assert mock_qdrant_client.collection_exists.call_count == 3
    assert mock_qdrant_client.create_collection.call_count == 3

    # Check that all collections were created with correct names
    created_collections = [
        call_args[0][0] if call_args[0] else call_args[1].get("collection_name")
        for call_args in mock_qdrant_client.create_collection.call_args_list
    ]
    assert "agent_memory" in created_collections
    assert "knowledge_base" in created_collections
    assert "trading_context" in created_collections


@pytest.mark.asyncio
async def test_collection_creation_idempotent(mock_qdrant_client, mock_embedding_service):
    """Collection creation should be idempotent (safe to call multiple times)."""
    mock_qdrant_client.collection_exists.return_value = True

    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    # Should check existence but NOT create (already exists)
    assert mock_qdrant_client.collection_exists.call_count == 3
    assert mock_qdrant_client.create_collection.call_count == 0


@pytest.mark.asyncio
async def test_add_embeds_and_upserts(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.add should embed summaries and upsert to collection."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    items = [
        {
            "id": "item_1",
            "summary": "Test summary",
            "area": "main",
            "project": "test_project",
        }
    ]

    await backend.add(items, test_context)

    # Should embed the summary
    mock_embedding_service.embed.assert_called_once()
    call_args = mock_embedding_service.embed.call_args
    # embed() is called with keyword arguments: texts, project_id, model, normalize
    assert "Test summary" in call_args.kwargs["texts"]
    assert call_args.kwargs["project_id"] == "test_project"

    # Should upsert to collection
    mock_qdrant_client.upsert.assert_called_once()
    upsert_call = mock_qdrant_client.upsert.call_args
    assert upsert_call[1]["collection_name"] == "agent_memory"

    # Check payload includes schema_version
    points = upsert_call[1]["points"]
    assert len(points) == 1
    assert points[0].payload["schema_version"] == "v1"
    assert points[0].payload["project"] == "test_project"


@pytest.mark.asyncio
async def test_search_enforces_project_filter(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.search should ALWAYS include project filter."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    await backend.search("test query", top_k=5, context=test_context)

    # Should call search with filter
    mock_qdrant_client.search.assert_called_once()
    search_call = mock_qdrant_client.search.call_args
    query_filter = search_call[1]["query_filter"]

    # Filter should contain project condition
    assert query_filter is not None
    # This is a basic check - actual Filter structure depends on implementation


@pytest.mark.asyncio
async def test_search_with_area_filter(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.search with area should add area filter."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    await backend.search("test query", top_k=5, context=test_context, area="main")

    # Should call search with both project and area filters
    mock_qdrant_client.search.assert_called_once()


@pytest.mark.asyncio
async def test_search_graceful_degradation(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.search should return empty list when Qdrant unavailable."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    # Simulate Qdrant failure
    mock_qdrant_client.search.side_effect = Exception("Qdrant unavailable")

    results = await backend.search("test query", top_k=5, context=test_context)

    # Should return empty list, not raise exception
    assert results == []


@pytest.mark.asyncio
async def test_search_success_reports_embedding_healthy_on_recovery(
    mock_qdrant_client, mock_embedding_service, test_context
):
    """WR-03: a successful embed must report embedding healthy so a prior transient
    embedding fault does NOT stick as a false 'DEGRADED (embedding unavailable)'.

    Seeds the shared SourceHealthRegistry with a sticky embedding=unavailable (as the
    failure path leaves it), runs a successful search, and asserts the record flipped
    back to available=True — the hits-first recovery pattern the failure-only reporting
    never provided.
    """
    from emitters.source_health_registry import SourceHealthRegistry

    reg = SourceHealthRegistry.get_shared_instance()
    reg.report("embedding", available=False, failure_reason="RuntimeError")
    assert reg.snapshot()["embedding"].available is False

    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    # A well-formed (empty) query_points result — the success path still freshens
    # embedding health even with zero hits.
    resp = Mock()
    resp.points = []
    mock_qdrant_client.query_points = Mock(return_value=resp)

    await backend.search("test query", top_k=5, context=test_context)

    assert reg.snapshot()["embedding"].available is True, (
        "a successful embed must clear the sticky DEGRADED embedding record (WR-03)"
    )


@pytest.mark.asyncio
async def test_delete_by_ids(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.delete should remove points by ID within project scope."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    await backend.delete(["id_1", "id_2"], test_context)

    # Should call delete with point IDs
    mock_qdrant_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_clear_removes_all_project_points(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.clear should remove all points for project."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    await backend.clear(test_context)

    # Should call delete with filter for project
    mock_qdrant_client.delete.assert_called_once()
    delete_call = mock_qdrant_client.delete.call_args
    assert delete_call[1]["collection_name"] == "agent_memory"


@pytest.mark.asyncio
async def test_add_handles_qdrant_unavailable(mock_qdrant_client, mock_embedding_service, test_context):
    """QdrantBackend.add should log error but not crash when Qdrant unavailable."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )

    # Simulate Qdrant failure
    mock_qdrant_client.upsert.side_effect = Exception("Qdrant unavailable")

    items = [{"id": "item_1", "summary": "Test", "area": "main", "project": "test_project"}]

    # Should not raise exception
    await backend.add(items, test_context)
