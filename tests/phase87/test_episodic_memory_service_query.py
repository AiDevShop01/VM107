"""Phase 87 Wave 4a query roundtrip — seed 5 episodes, query similar, get top-K.

Per LOCK-6: top_k defaults to 5 (Brain Part 2 default K=3; Phase 87 widens for
narrative + transmission breadth).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.phase_87


def _qdrant_url_from_test_client(qdrant_test_client) -> str:
    """Conftest creates QdrantClient(host=..., port=...); QdrantRemote stores
    them as private `_host` / `_port` (verified against qdrant_client v1.7)."""
    remote = qdrant_test_client._client
    return f"http://{remote._host}:{remote._port}"


def _seed_episodes(qdrant_client, count=5, indicator_id="CPIAUCSL"):
    from qdrant_client.http import models as qm
    from VM107.core.memory.qdrant_macro_episode_collection import COLLECTION_NAME
    points = []
    for i in range(count):
        ep_id = uuid.uuid4()
        points.append(qm.PointStruct(
            id=str(ep_id),
            vector=[float(i) / 100] * 768,  # easy deterministic vectors
            payload={
                "episode_id": str(ep_id),
                "indicator_id": indicator_id,
                "regime_at_episode": "inflation",
                "release_date": "2022-03-10",
                "decay_weight": 1.0 - (i * 0.1),
                "episode_text": f"CPI release #{i}",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        ))
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)


def test_query_returns_top_k_5_default(qdrant_test_client, monkeypatch):
    from VM107.core.memory.episodic_memory_service import (
        EpisodicMemoryService, EpisodicQuery,
    )

    monkeypatch.setenv("QDRANT_URL", _qdrant_url_from_test_client(qdrant_test_client))
    _seed_episodes(qdrant_test_client, count=20)

    embedding_stub = MagicMock()
    embedding_stub.embed.return_value = [0.5] * 768

    svc = EpisodicMemoryService(embedding_service=embedding_stub)
    q = EpisodicQuery(
        query_id=uuid.uuid4(),
        requesting_profile="macro_story_tracker",
        requesting_sub_profile=None,
        query_text="CPI surprise +0.1",
        query_embedding=None,
        scope={"collection": "macro_episode"},
        top_k=5,
        memory_types_requested=["episodic"],
        timestamp=datetime.now(tz=timezone.utc),
    )
    result = svc.query(q)
    assert len(result.memories_retrieved) == 5
    assert all(m.memory_type == "episodic" for m in result.memories_retrieved)
    assert all(
        m.citations[0].citation_ref.startswith("[ref:episode:")
        for m in result.memories_retrieved
    )


def test_query_returns_list_even_for_empty_match(qdrant_test_client, monkeypatch):
    from VM107.core.memory.episodic_memory_service import (
        EpisodicMemoryService, EpisodicQuery,
    )

    monkeypatch.setenv("QDRANT_URL", _qdrant_url_from_test_client(qdrant_test_client))
    embedding_stub = MagicMock()
    embedding_stub.embed.return_value = [0.5] * 768
    svc = EpisodicMemoryService(embedding_service=embedding_stub)
    result = svc.query(EpisodicQuery(
        query_id=uuid.uuid4(),
        requesting_profile="x", requesting_sub_profile=None,
        query_text="anything",
        query_embedding=None, scope={"collection": "macro_episode"},
        top_k=5, memory_types_requested=["episodic"],
        timestamp=datetime.now(tz=timezone.utc),
    ))
    assert isinstance(result.memories_retrieved, list)


def test_fails_fast_without_qdrant_url(monkeypatch):
    from VM107.core.memory.episodic_memory_service import EpisodicMemoryService

    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(RuntimeError, match="QDRANT_URL"):
        EpisodicMemoryService(embedding_service=MagicMock())
