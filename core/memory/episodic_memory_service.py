"""Phase 87 Wave 4a — Brain B6 EpisodicMemoryService.

Per Brain Part 2 §B6 contract. Env-driven config — fails fast at construction
if QDRANT_URL is missing (no default fallback, per the project no-fallback
lock).

Public surface (re-exported via ``VM107.core.memory.__init__``):
    - EpisodicMemoryService — the service class.
    - EpisodicQuery — input contract.
    - EpisodicResult — output envelope.
    - MemoryRecord — one retrieved memory.
    - CitationRef — Phase 71 evidence drawer citation grammar.

Behavioural locks (LOCK-6, Plan 87-07):
    - Default top-K = 5 (Brain Part 2 default is 3; Phase 87 widens for
      narrative + transmission breadth).
    - Re-rank: ``decay_weight × cosine_score`` (over-fetches 3x then sorts).
    - Citation grammar: ``[ref:episode:<uuid>]`` — Phase 71 drawer parses
      this verbatim.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from qdrant_client import QdrantClient

from VM107.core.memory.qdrant_macro_episode_collection import (
    COLLECTION_NAME,
    ensure_macro_episode_collection,
)


# ─── Dataclasses (Brain Part 2 §B6 verbatim contract) ───────────────────────
@dataclass(frozen=True)
class CitationRef:
    """Phase 71 evidence drawer citation. ``citation_ref`` is the user-visible
    token; ``kind`` is "episode" | "release" | "indicator"; ``target_id`` is
    the bare id."""

    citation_ref: str
    kind: str
    target_id: str


@dataclass(frozen=True)
class MemoryRecord:
    """One memory returned by ``EpisodicMemoryService.query``. ``embedding``
    is the original 768-dim vector for re-ranking by downstream consumers;
    ``decay_weight`` is the temporal decay factor applied during retrieval."""

    memory_id: uuid.UUID
    memory_type: Literal["episodic"]
    text: str
    embedding: list[float]
    created_at: datetime
    decay_weight: float
    citations: list[CitationRef]


@dataclass(frozen=True)
class EpisodicQuery:
    """Input contract. ``query_embedding`` may be ``None``; the service then
    computes it via the injected ``embedding_service``. ``scope`` carries the
    collection name (Phase 87: ``{"collection": "macro_episode"}``)."""

    query_id: uuid.UUID
    requesting_profile: str
    requesting_sub_profile: str | None
    query_text: str
    query_embedding: list[float] | None
    scope: dict
    top_k: int
    memory_types_requested: list[str]
    timestamp: datetime


@dataclass(frozen=True)
class EpisodicResult:
    """Output envelope. ``confidence`` is the top hit's composite score
    (``decay_weight × cosine``) or 0.0 when no memories were retrieved."""

    query_id: uuid.UUID
    memories_retrieved: list[MemoryRecord]
    retrieval_latency_ms: int
    cache_hit: bool
    confidence: float


# ─── Service ───────────────────────────────────────────────────────────────
class EpisodicMemoryService:
    """Brain B6 RAG service. Constructed once per agent runtime; thread-safe
    for read-only ``query`` calls (Qdrant client is HTTP-based).

    Args:
        qdrant_url: Optional explicit URL. If absent, ``QDRANT_URL`` env var
            is required (fail-fast at construction — no default fallback).
        embedding_service: Object with a synchronous ``embed(text) -> list[float]``
            method. In production this is the Phase 58 all-mpnet-base-v2
            singleton; in tests it can be a ``MagicMock``.
        collection_name: Qdrant collection name (default ``macro_episode``).
        top_k_default: Default top-K when ``EpisodicQuery.top_k`` is falsy
            (default 5 — LOCK-6).
    """

    def __init__(
        self,
        *,
        qdrant_url: str | None = None,
        embedding_service,
        collection_name: str = COLLECTION_NAME,
        top_k_default: int = 5,  # LOCK-6
    ) -> None:
        url = qdrant_url or os.environ.get("QDRANT_URL")
        if not url:
            raise RuntimeError(
                "QDRANT_URL required — env-driven config, no default fallback "
                "(CLAUDE.md no-fallback-defaults lock)"
            )
        # check_compatibility=False — testcontainers ship Qdrant 1.7 while
        # the client library is 1.18; the API surface used here is stable.
        self._client = QdrantClient(url=url, check_compatibility=False)
        ensure_macro_episode_collection(self._client)
        self._embedding = embedding_service
        self._collection = collection_name
        self._top_k_default = top_k_default

    def query(self, q: EpisodicQuery) -> EpisodicResult:
        """Retrieve top-K episodes for the query, re-ranked by
        ``decay_weight × cosine_score``.

        Over-fetches by 3x (or min 15) from Qdrant so the re-rank has enough
        breadth to surface a high-decay-low-cosine candidate over a
        low-decay-high-cosine one.
        """
        t0 = time.monotonic()
        scope_collection = q.scope.get("collection", self._collection)
        top_k = q.top_k or self._top_k_default

        vec = q.query_embedding or self._embedding.embed(q.query_text)
        # qdrant_client v1.10+ replaces .search() with .query_points(); response
        # is a QueryResponse envelope with .points carrying the scored hits.
        response = self._client.query_points(
            collection_name=scope_collection,
            query=vec,
            limit=max(top_k * 3, 15),
            with_payload=True,
            with_vectors=True,
        )

        scored: list[tuple[float, MemoryRecord]] = []
        for hit in response.points:
            payload = hit.payload or {}
            decay = float(payload.get("decay_weight", 1.0))
            composite = decay * float(hit.score)

            # Prefer the explicit payload episode_id; fall back to the point
            # id (which is always a str-of-uuid in our ingest path).
            raw_id = payload.get("episode_id") or str(hit.id)
            try:
                mem_id = uuid.UUID(raw_id)
            except (TypeError, ValueError):
                mem_id = uuid.uuid4()

            created_raw = payload.get("created_at")
            try:
                created_at = (
                    datetime.fromisoformat(created_raw)
                    if created_raw
                    else datetime.now(tz=timezone.utc)
                )
            except (TypeError, ValueError):
                created_at = datetime.now(tz=timezone.utc)

            scored.append((composite, MemoryRecord(
                memory_id=mem_id,
                memory_type="episodic",
                text=str(payload.get("episode_text", "")),
                embedding=list(hit.vector or []),
                created_at=created_at,
                decay_weight=decay,
                citations=[CitationRef(
                    citation_ref=f"[ref:episode:{mem_id}]",
                    kind="episode",
                    target_id=str(mem_id),
                )],
            )))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [mem for _, mem in scored[:top_k]]
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        confidence = float(scored[0][0]) if scored else 0.0

        return EpisodicResult(
            query_id=q.query_id,
            memories_retrieved=top,
            retrieval_latency_ms=elapsed_ms,
            cache_hit=False,
            confidence=confidence,
        )
