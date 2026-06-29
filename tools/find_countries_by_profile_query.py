"""Phase 96 REQ-96-8 — Qdrant cross-country semantic search tool.

`find_countries_by_profile_query` runs natural-language queries against the
loaded `country_profiles` Qdrant collection (per-country narrative sections),
deduplicates by country (highest score wins), and returns a ranked country
list with section evidence.

Pattern (from 96-RESEARCH.md §Pattern 8):
- ContractTool subclass (VM107/tools/vm_contracts/base.py) for agent registration
- Pydantic request/response from fingpt_core.contracts.economic_intelligence.country_search
- Env-driven QDRANT_URL + QDRANT_API_KEY — fail-fast at construction, no
  os.getenv('X', 'default') fallback (Phase 47.6 env-driven-config lock)
- Graceful degradation: Qdrant down → empty countries[] + structured error log
- Structured INFO log: {event, query_hash, top_k, latency_ms, result_count}

Consumers (per registry YAML vm107.tool.find_countries_by_profile_query):
- vm107.country_dna_generator (Plan 96-05) — invokes per STRUCTURAL_QUERY_TEMPLATE
- vm107.macro_ask_router (Phase 94) — routes "find countries with X" prompts
- WorldMap "color countries matching query" (Plan 96-09)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)

from fingpt_core.contracts.economic_intelligence.country_search import (
    CountryHit,
    FindCountriesByProfileRequest,
    FindCountriesByProfileResponse,
)

# ContractTool import — use the actual VM107 path. Production runs in the
# VM107 container with `tools.*` on sys.path; tests use the conftest at
# VM107/conftest.py which ensures the same. host-shell fallback shim mirrors
# the GraphSearchTool pattern (VM107/tools/graph/graph_search_tool.py:14-37).
try:  # Production import (VM107 container with tools on sys.path).
    from tools.vm_contracts.base import ContractTool  # type: ignore
except Exception:  # pragma: no cover - host-shell fallback for isolated tests.
    class ContractTool:  # type: ignore
        """Minimal shim so this module imports without VM107's full Tool stack."""
        pass


logger = logging.getLogger("tools.find_countries_by_profile_query")


# Re-export the contracts so tests can import them via this module too.
__all__ = [
    "FindCountriesByProfileQueryTool",
    "FindCountriesByProfileRequest",
    "FindCountriesByProfileResponse",
    "CountryHit",
]


# Plan 06 must_have: max sections of evidence per country in the response.
_MAX_EVIDENCE_PER_COUNTRY = 3
# Plan 06 must_have: narrative snippet truncated at 200 chars (citation-ready).
_NARRATIVE_SNIPPET_LEN = 200
# Plan 06 must_have: overscan limit for Qdrant search — top_k * 3 gives
# headroom after dedup-by-country collapses near-duplicates.
_OVERSCAN_MULTIPLIER = 3
# Plan 06 must_have: Qdrant collection that holds country-profile narrative vectors.
_COLLECTION_NAME = "country_profiles"


class FindCountriesByProfileQueryTool(ContractTool):
    """Qdrant cross-country semantic search — REQ-96-8.

    Public API:
        run(request: FindCountriesByProfileRequest) -> FindCountriesByProfileResponse

    The sync `run()` surface is what Plan 96-05's DNA agent + Phase 94's macro
    ask router call directly (mirrors GraphSearchTool.run_template). Agent-zero
    ContractTool's async `execute()` pipeline (validate_request → call_vm →
    validate_response) is not used because this tool runs in-process — there is
    no remote VM to call.
    """

    name = "find_countries_by_profile_query"
    # Class-level metadata for registry introspection (matches the YAML at
    # VM107/registry/tool/vm107.tool.find_countries_by_profile_query.yaml).
    request_model = FindCountriesByProfileRequest
    response_model = FindCountriesByProfileResponse

    def __init__(
        self,
        qdrant_client: QdrantClient | None = None,
        embedder: Any | None = None,
    ) -> None:
        """Construct the tool.

        Env-driven, fail-fast:
        - QDRANT_URL is REQUIRED — missing → KeyError (no silent default).
        - QDRANT_API_KEY is optional (None when absent).

        Args:
            qdrant_client: Inject a QdrantClient for tests; defaults to one
                built from QDRANT_URL/QDRANT_API_KEY env.
            embedder: Inject a sync embedder exposing `.embed(text: str) -> list[float]`
                for tests; defaults to the production sentence-transformers loader.
        """
        # Fail-fast env read (Phase 47.6 lock — feedback_env_driven_no_fallbacks).
        qdrant_url = os.environ["QDRANT_URL"]
        qdrant_api_key = os.environ.get("QDRANT_API_KEY") or None
        self.qdrant = qdrant_client or QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        self.embedder = embedder if embedder is not None else self._default_embedder()

    # ------------------------------------------------------------------
    # Sync run — direct in-process call from Plan 05 DNA agent + tests.
    # ------------------------------------------------------------------

    def run(self, request: FindCountriesByProfileRequest) -> FindCountriesByProfileResponse:
        """Execute the search + dedup-by-country pipeline.

        Pipeline:
        1. Hash query for log correlation.
        2. Embed the query string via the injected embedder.
        3. Build the Qdrant Filter from section_filter + country_filter.
        4. Search the country_profiles collection (overscan = top_k * 3).
        5. Aggregate raw hits by country_iso — highest score wins; up to
           _MAX_EVIDENCE_PER_COUNTRY sections kept per country.
        6. Sort countries by best score desc, slice top_k.
        7. Emit structured INFO log + return FindCountriesByProfileResponse.

        Graceful degradation: any exception from embedder / Qdrant → empty
        response + structured ERROR log + non-zero latency_ms. Tool never raises.
        """
        t0 = time.monotonic()
        query_hash = hashlib.md5(request.query.encode("utf-8")).hexdigest()

        try:
            vector = self.embedder.embed(request.query)
            query_filter = self._build_filter(request)
            raw_hits = self.qdrant.search(
                collection_name=_COLLECTION_NAME,
                query_vector=vector,
                query_filter=query_filter,
                limit=request.top_k * _OVERSCAN_MULTIPLIER,
            )
        except Exception as exc:  # pragma: no cover - covered via test_qdrant_search_failure
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                json.dumps(
                    {
                        "event": "qdrant_search_failed",
                        "tool": self.name,
                        "query_hash": query_hash,
                        "latency_ms": latency_ms,
                        "error": str(exc),
                    }
                )
            )
            return FindCountriesByProfileResponse(
                countries=[],
                query_hash=query_hash,
                latency_ms=latency_ms,
            )

        country_hits = self._dedup_by_country(raw_hits, min_score=request.min_score)
        top = sorted(country_hits.values(), key=lambda c: c["score"], reverse=True)[: request.top_k]
        latency_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            json.dumps(
                {
                    "event": "find_countries_by_profile_query",
                    "tool": self.name,
                    "query_hash": query_hash,
                    "top_k": request.top_k,
                    "latency_ms": latency_ms,
                    "result_count": len(top),
                }
            )
        )

        return FindCountriesByProfileResponse(
            countries=[CountryHit(**c) for c in top],
            query_hash=query_hash,
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(request: FindCountriesByProfileRequest) -> Filter | None:
        """Translate request filters → Qdrant Filter(must=[FieldCondition...]).

        Returns None when neither filter is set so the Qdrant call is unfiltered.
        """
        conditions: list[FieldCondition] = []
        if request.section_filter:
            conditions.append(
                FieldCondition(
                    key="section_type",
                    match=MatchValue(value=request.section_filter),
                )
            )
        if request.country_filter:
            conditions.append(
                FieldCondition(
                    key="country_iso",
                    match=MatchAny(any=request.country_filter),
                )
            )
        return Filter(must=conditions) if conditions else None

    @staticmethod
    def _dedup_by_country(raw_hits: Any, *, min_score: float) -> dict[str, dict]:
        """Collapse raw Qdrant hits to one entry per country.

        Strategy:
        - First hit per country becomes the canonical entry (carries the best
          score because raw_hits arrive sorted desc by score from Qdrant).
        - Subsequent hits for the same country are appended to section_evidence
          (up to _MAX_EVIDENCE_PER_COUNTRY) so the DNA agent has multi-section
          context for the country.
        - Hits below min_score are dropped.
        - Hits missing country_iso payload field are dropped (data hygiene —
          should never happen on a well-loaded collection but be defensive).

        Returns a dict keyed by ISO alpha-2 to make the post-filter sort cheap.
        """
        by_country: dict[str, dict] = {}
        for hit in raw_hits:
            if hit.score < min_score:
                continue
            payload = hit.payload or {}
            iso = payload.get("country_iso")
            if not iso:
                continue

            evidence_entry = {
                "section_type": payload.get("section_type"),
                "section_id": payload.get("section_id"),
                "narrative_snippet": (payload.get("narrative") or "")[:_NARRATIVE_SNIPPET_LEN],
                "score": float(hit.score),
            }

            existing = by_country.get(iso)
            if existing is None:
                by_country[iso] = {
                    "iso_alpha2": iso,
                    "country_name": payload.get("country_name", iso),
                    "score": float(hit.score),
                    "section_evidence": [evidence_entry],
                }
            else:
                # Higher score never seen first because Qdrant sorts desc, but
                # guard anyway in case the input iterator is reshaped upstream.
                if float(hit.score) > existing["score"]:
                    existing["score"] = float(hit.score)
                if len(existing["section_evidence"]) < _MAX_EVIDENCE_PER_COUNTRY:
                    existing["section_evidence"].append(evidence_entry)
        return by_country

    @staticmethod
    def _default_embedder() -> Any:
        """Production embedder — loaded lazily so tests can inject a mock.

        Uses BgeEmbeddingAdapter (BAAI/bge-base-en-v1.5, 768-dim) from the
        memory-plugin adapters, wrapped in a sync shim because that adapter is
        async. Lazy import keeps sentence-transformers off the import path
        when callers inject their own embedder (the common test path).
        """
        from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter
        import asyncio

        adapter = BgeEmbeddingAdapter()

        class _SyncEmbedderShim:
            MODEL_NAME = adapter.MODEL_NAME
            VECTOR_DIM = adapter.VECTOR_DIM

            def embed(self, text: str) -> list[float]:
                response = asyncio.run(adapter.embed([text]))
                return response.embeddings[0]

        return _SyncEmbedderShim()
