"""search_knowledge tool — LOCAL Qdrant default; VM101 is a flag-gated fallback.

Phase 136 / P4 (D-02 + D-03) supersedes the Phase 42.1 HTTP-only lock: the tool
now reads the ``knowledge_base_v2/general_embedding`` corpus DIRECTLY via the
proven ``Memory._get_knowledge_v2_backend()`` local-Qdrant reader (no VM101
runtime hop on the happy path). VM101's ``POST /api/v1/knowledge/search`` is
retained ONLY as a fallback, fired exclusively on a LOCAL ERROR and gated behind
the ``SEARCH_KNOWLEDGE_VM101_FALLBACK`` flag (default OFF).

Honest degradation (D-03, carried from Phase 135): ``QdrantBackend.search`` never
raises — it returns ``[]`` for BOTH a genuine empty corpus AND a local outage, and
reports the outage to ``SourceHealthRegistry`` instead. So the return value alone
cannot tell an outage from an empty result. We DISCRIMINATE by reading the health
bus, keyed by this agent's immutable ``context.id`` (the 135-06 object-carried
per-context key — NEVER the shared-mutable per-request ContextVar, whose race was
the 135-D3 defect). A local error surfaces a typed DEGRADED signal
naming the failing SUBSYSTEM only (``type(e).__name__``-class discipline, T-135-01:
never ``str(e)``, host:port, ``6333``, or an IP) — and the DEGRADED signal STANDS
even when the VM101 fallback then succeeds (they compose). An empty-but-successful
local result is a GENUINE empty and does NOT fall back to VM101 (Pitfall 2 / D-02).

Endpoint contract (VM101 fallback only, from 42.1-CONTEXT.md):
  POST /api/v1/knowledge/search
  Request:  {"query": str, "top_k": int = 5, "filters": dict | None}
  Response: {"results": [{"text": str, "score": float, "metadata": dict}, ...]}
"""
import os
import httpx

from helpers.tool import Tool, Response


# Fail-fast env read (D-04): a missing VM101 fallback URL raises at import, never a
# silent literal-IP default. The fallback is off by default, but the URL stays
# required so a misconfigured fallback surfaces at boot, not at first use.
VM101_KB_SEARCH_URL = os.environ["VM101_KB_SEARCH_URL"]

_FALLBACK_ENV = "SEARCH_KNOWLEDGE_VM101_FALLBACK"


def _vm101_fallback_enabled() -> bool:
    """Whether the VM101 HTTP fallback is enabled (default OFF)."""
    return os.environ.get(_FALLBACK_ENV, "").strip().lower() in ("1", "true", "yes", "on")


class SearchKnowledgeTool(Tool):
    """Semantic search over knowledge_base_v2 — local Qdrant first, VM101 fallback."""

    async def execute(self, **kwargs):
        # --- Input validation (retained verbatim, V5 / T-136-08) ---
        query = kwargs.get("query", "").strip()
        if not query:
            return Response(
                message="Error: search_knowledge requires a non-empty 'query' arg.",
                break_loop=False,
            )

        top_k = kwargs.get("top_k", 5)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 5

        filters = kwargs.get("filters") or None

        # --- Local Qdrant read (the default path, D-02) ---
        # QdrantBackend.search NEVER raises; it returns [] on both error and empty and
        # reports any outage to SourceHealthRegistry. We swallow setup-time failures
        # here WITHOUT self-reporting or leaking the exception — the health bus is the
        # single error-vs-empty discriminator (read below), exactly as the native
        # recall reader does (_50_recall_memories.py:154-190).
        hits = []
        backend_missing = False
        try:
            from plugins._memory.helpers.memory import Memory, _QdrantContext

            db = await Memory.get(self.agent)  # stamps db.context_id = agent.context.id (135-06)
            v2 = db._get_knowledge_v2_backend()
            if v2 is None:
                backend_missing = True
            else:
                ctx = _QdrantContext(
                    db.memory_subdir, context_id=getattr(db, "context_id", None)
                )
                hits = await v2.search(query=query, top_k=top_k, context=ctx, area=None) or []
        except Exception:
            # Do NOT leak type/str of the exception into the tool response; do NOT
            # self-report to the bus. Fall through to the health-bus discriminator.
            hits = []

        # --- Error-vs-empty discrimination via the health bus (D-02 + D-03) ---
        # Object-carried per-context key (agent.context.id) — NEVER the shared-mutable
        # per-request ContextVar (135-D3 race). Ctxid key first, then bare-key (C floor).
        from emitters.source_health_registry import SourceHealthRegistry

        ctxid = getattr(getattr(self.agent, "context", None), "id", "") or ""
        snap = SourceHealthRegistry.get_shared_instance().snapshot()
        qh = (snap.get(f"qdrant:{ctxid}") if ctxid else None) or snap.get("qdrant")
        eh = (snap.get(f"embedding:{ctxid}") if ctxid else None) or snap.get("embedding")

        # Check embedding BEFORE qdrant (report("embedding", available=True) is never
        # called, so eh is None means embedding succeeded this call — do NOT infer
        # embedding success from the bus, only failure).
        degraded_subsystem = None
        if eh is not None and eh.available is False:
            degraded_subsystem = "embedding"
        elif qh is not None and qh.available is False:
            degraded_subsystem = "qdrant"
        elif backend_missing:
            # No local knowledge backend to borrow — treat as a local outage.
            degraded_subsystem = "qdrant"

        if degraded_subsystem is not None:
            return await self._degraded_response(degraded_subsystem, query, top_k, filters)

        # Local path healthy. Empty is a GENUINE empty — NO VM101 fallback (Pitfall 2).
        if not hits:
            return Response(
                message=f"No results found for query: {query!r}",
                break_loop=False,
            )

        return Response(message=self._format_local_hits(hits, query), break_loop=False)

    # ------------------------------------------------------------------ #
    # DEGRADED signal (D-03) + flag-gated VM101 fallback (D-02)          #
    # ------------------------------------------------------------------ #
    async def _degraded_response(self, subsystem, query, top_k, filters):
        """Return the typed DEGRADED signal (T-135-01 leak-safe) + optional fallback.

        The message names the failing SUBSYSTEM class only — never str(e), a
        host:port, ``6333``, or an IP. The DEGRADED signal STANDS even when the
        VM101 fallback succeeds (they compose).
        """
        if subsystem == "embedding":
            degraded = (
                "Knowledge search DEGRADED (embedding service unavailable) — the local "
                "knowledge subsystem is impaired, not empty; results may be incomplete. "
                "Do not claim the knowledge base is empty."
            )
        else:
            degraded = (
                "Knowledge search DEGRADED (qdrant unreachable) — the local knowledge "
                "subsystem is impaired, not empty; results may be incomplete. Do not "
                "claim the knowledge base is empty."
            )

        if not _vm101_fallback_enabled():
            return Response(message=degraded, break_loop=False)

        fallback = await self._vm101_search(query, top_k, filters)
        return Response(message=f"{degraded}\n\n{fallback}", break_loop=False)

    async def _vm101_search(self, query, top_k, filters):
        """VM101 HTTP fallback — invoked ONLY on a local error, behind the flag."""
        payload = {"query": query, "top_k": top_k}
        if filters:
            payload["filters"] = filters

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(VM101_KB_SEARCH_URL, json=payload)
        except httpx.RequestError as e:
            # Leak-safe: name the failure CLASS only, never host:port/IP.
            return f"VM101 fallback unreachable ({type(e).__name__})."

        if resp.status_code != 200:
            return f"VM101 fallback returned HTTP {resp.status_code}."

        try:
            data = resp.json()
        except ValueError:
            return "VM101 fallback returned a non-JSON response."

        results = data.get("results", []) or []
        if not results:
            return f"VM101 fallback found no results for query: {query!r}"

        lines = [f"VM101 fallback found {len(results)} result(s) for: {query!r}\n"]
        for i, hit in enumerate(results, 1):
            text = (hit.get("text") or "").strip()
            score = hit.get("score", 0.0)
            meta = hit.get("metadata") or {}
            title = meta.get("title", "")
            author = meta.get("author", "")
            chunk_id = meta.get("chunk_id", meta.get("chunk_index", ""))
            attribution_parts = [
                p for p in [title, author, f"chunk {chunk_id}" if chunk_id != "" else ""] if p
            ]
            attribution = " · ".join(attribution_parts) if attribution_parts else "unknown source"
            lines.append(f"### Result {i} (score={score:.3f}, {attribution})")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Local hit formatting                                               #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _format_local_hits(hits, query):
        """Format local knowledge_base_v2 hits (title/text idiom from memory.py:690-696)."""
        lines = [f"Found {len(hits)} result(s) for: {query!r}\n"]
        for i, hit in enumerate(hits, 1):
            title = hit.get("book_title") or hit.get("source_file") or "knowledge"
            text = (hit.get("text", "") or hit.get("content", "") or "").strip()
            score = hit.get("score", 0.0)
            try:
                score_str = f"{float(score):.3f}"
            except (TypeError, ValueError):
                score_str = str(score)
            lines.append(f"### Result {i} (score={score_str}, {title})")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)
