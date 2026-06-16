"""Phase 87 Wave 4a — macro_episode Qdrant collection bootstrap.

Per Qdrant best practices: create payload indexes BEFORE ingesting data so
the HNSW filterable index is built alongside the vector index. Idempotent —
second call is a no-op (existing collection / existing indexes are tolerated).

Schema:
    - Vector: 768-dim, COSINE distance (all-mpnet-base-v2 embedding space,
      shared with Phase 58 trade-intelligence trade_episode collection).
    - Indexed payload fields (KEYWORD): indicator_id, regime_at_episode,
      release_date.
    - Unindexed payload fields: surprise (float), decay_weight (float),
      episode_text (text), created_at (ISO datetime).
"""
from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION_NAME = "macro_episode"
VECTOR_SIZE = 768
DISTANCE = qm.Distance.COSINE

# Payload fields that must be indexed for filterable HNSW.
_INDEXED_FIELDS: tuple[tuple[str, qm.PayloadSchemaType], ...] = (
    ("indicator_id", qm.PayloadSchemaType.KEYWORD),
    ("regime_at_episode", qm.PayloadSchemaType.KEYWORD),
    ("release_date", qm.PayloadSchemaType.KEYWORD),
)


def ensure_macro_episode_collection(client: QdrantClient) -> None:
    """Create the ``macro_episode`` collection if absent + ensure payload
    indexes are present. Idempotent.

    Args:
        client: Live ``QdrantClient``. Caller owns lifecycle (do not close).
    """
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qm.VectorParams(size=VECTOR_SIZE, distance=DISTANCE),
        )

    for field, schema in _INDEXED_FIELDS:
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=schema,
            )
        except Exception:  # noqa: BLE001
            # Qdrant returns 200 with a "already exists" status for idempotent
            # re-runs in some versions; in others it raises. Either is fine.
            continue
