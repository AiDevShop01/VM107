"""LOCK-6 top-K=5 boundary — fewer in collection than top_k → return all available.

Brain Part 2 §B6 contract: never pad results; return what's there.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.phase_87


def _qdrant_url_from_test_client(qdrant_test_client) -> str:
    remote = qdrant_test_client._client
    return f"http://{remote._host}:{remote._port}"


def test_topk_3_episodes_returns_3_not_5(qdrant_test_client, monkeypatch):
    """When collection has fewer than top_k records, return what's there."""
    from qdrant_client.http import models as qm
    from VM107.core.memory.episodic_memory_service import (
        EpisodicMemoryService, EpisodicQuery,
    )
    from VM107.core.memory.qdrant_macro_episode_collection import COLLECTION_NAME

    monkeypatch.setenv("QDRANT_URL", _qdrant_url_from_test_client(qdrant_test_client))
    # clear by recreating collection — service constructor re-bootstraps
    qdrant_test_client.delete_collection(COLLECTION_NAME)
    embedding_stub = MagicMock()
    embedding_stub.embed.return_value = [0.5] * 768
    svc = EpisodicMemoryService(embedding_service=embedding_stub)
    # Now seed exactly 3
    points = []
    for i in range(3):
        ep_id = uuid.uuid4()
        points.append(qm.PointStruct(
            id=str(ep_id),
            vector=[float(i) / 100] * 768,
            payload={
                "episode_id": str(ep_id),
                "indicator_id": "CPIAUCSL",
                "decay_weight": 1.0,
                "episode_text": f"ep {i}",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        ))
    qdrant_test_client.upsert(collection_name=COLLECTION_NAME, points=points)

    result = svc.query(EpisodicQuery(
        query_id=uuid.uuid4(),
        requesting_profile="x", requesting_sub_profile=None,
        query_text="x", query_embedding=None,
        scope={"collection": "macro_episode"}, top_k=5,
        memory_types_requested=["episodic"],
        timestamp=datetime.now(tz=timezone.utc),
    ))
    assert len(result.memories_retrieved) == 3


def test_decay_weight_reranks_top_results(qdrant_test_client, monkeypatch):
    """Highest decay × score wins, not raw cosine alone — verify by seeding
    one episode with low decay but high vector similarity vs one with high
    decay but lower vector similarity."""
    from qdrant_client.http import models as qm
    from VM107.core.memory.episodic_memory_service import (
        EpisodicMemoryService, EpisodicQuery,
    )
    from VM107.core.memory.qdrant_macro_episode_collection import COLLECTION_NAME

    monkeypatch.setenv("QDRANT_URL", _qdrant_url_from_test_client(qdrant_test_client))
    qdrant_test_client.delete_collection(COLLECTION_NAME)
    embedding_stub = MagicMock()
    # query embedding will be all 0.5 — close to vector A (also 0.5 each)
    embedding_stub.embed.return_value = [0.5] * 768
    svc = EpisodicMemoryService(embedding_service=embedding_stub)

    # Episode A: very close vector but very low decay → low composite
    ep_a = uuid.uuid4()
    # Episode B: slightly less close vector but high decay → wins on composite
    ep_b = uuid.uuid4()
    points = [
        qm.PointStruct(
            id=str(ep_a), vector=[0.5] * 768,
            payload={
                "episode_id": str(ep_a),
                "indicator_id": "CPIAUCSL", "decay_weight": 0.01,
                "episode_text": "ancient CPI",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        ),
        qm.PointStruct(
            id=str(ep_b), vector=[0.49] * 768,
            payload={
                "episode_id": str(ep_b),
                "indicator_id": "CPIAUCSL", "decay_weight": 1.0,
                "episode_text": "recent CPI",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        ),
    ]
    qdrant_test_client.upsert(collection_name=COLLECTION_NAME, points=points)

    result = svc.query(EpisodicQuery(
        query_id=uuid.uuid4(),
        requesting_profile="x", requesting_sub_profile=None,
        query_text="x", query_embedding=None,
        scope={"collection": "macro_episode"}, top_k=2,
        memory_types_requested=["episodic"],
        timestamp=datetime.now(tz=timezone.utc),
    ))
    assert len(result.memories_retrieved) == 2
    # Recent (high decay) must rank first
    assert result.memories_retrieved[0].text == "recent CPI"
    assert result.memories_retrieved[1].text == "ancient CPI"
