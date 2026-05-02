"""Phase 42.1 search_knowledge tool — HTTP wrapper around VM101's knowledge endpoint.

Implements the locked Phase 42.1 design: HTTP-only contract with VM101's
POST /api/v1/knowledge/search. Does NOT depend on the broken fingpt_core
imports in tools/qdrant/search_knowledge.py — that file is intentionally dead
code per Phase 42.1 CONTEXT.md.

Tool dispatch: agent.get_tool() resolves tool_name="search_knowledge" by
looking for tools/search_knowledge.py via subagents.get_paths(). The previously
existing tools/qdrant/search_knowledge.py is in a SUBDIRECTORY and is NOT
discovered by that mechanism — which is why the tool has been silently
dispatching to Unknown ("Tool search_knowledge not found") since Phase 42.1.

Endpoint contract (from 42.1-CONTEXT.md):
  POST /api/v1/knowledge/search
  Request:  {"query": str, "top_k": int = 5, "filters": dict | None}
  Response: {"results": [{"text": str, "score": float, "metadata": dict}, ...]}
"""
import os
import httpx

from helpers.tool import Tool, Response


VM101_KB_SEARCH_URL = os.environ.get(
    "VM101_KB_SEARCH_URL",
    # Default for Docker Desktop / Mac: host.docker.internal reaches the host's
    # mapped port 8001 → vm101-backend container. In native Linux deployments
    # (e.g. Proxmox VM-to-VM) override via env to the actual VM101 host:port.
    "http://host.docker.internal:8001/api/v1/knowledge/search",
)


class SearchKnowledgeTool(Tool):
    """Semantic search over the ingested knowledge base via VM101's HTTP contract."""

    async def execute(self, **kwargs):
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

        payload = {"query": query, "top_k": top_k}
        if filters:
            payload["filters"] = filters

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(VM101_KB_SEARCH_URL, json=payload)
        except httpx.RequestError as e:
            return Response(
                message=f"Knowledge base unreachable at {VM101_KB_SEARCH_URL}: {e}",
                break_loop=False,
            )

        if resp.status_code != 200:
            return Response(
                message=(
                    f"Knowledge base returned HTTP {resp.status_code}: "
                    f"{resp.text[:300]}"
                ),
                break_loop=False,
            )

        try:
            data = resp.json()
        except ValueError:
            return Response(
                message=f"Knowledge base returned non-JSON: {resp.text[:300]}",
                break_loop=False,
            )

        results = data.get("results", []) or []
        if not results:
            return Response(
                message=f"No results found for query: {query!r}",
                break_loop=False,
            )

        # Format results as a readable list for the agent. Each item shows
        # score + source attribution + the chunk text itself.
        lines = [f"Found {len(results)} result(s) for: {query!r}\n"]
        for i, hit in enumerate(results, 1):
            text = (hit.get("text") or "").strip()
            score = hit.get("score", 0.0)
            meta = hit.get("metadata") or {}
            title = meta.get("title", "")
            author = meta.get("author", "")
            chunk_id = meta.get("chunk_id", meta.get("chunk_index", ""))
            attribution_parts = [p for p in [title, author, f"chunk {chunk_id}" if chunk_id != "" else ""] if p]
            attribution = " · ".join(attribution_parts) if attribution_parts else "unknown source"
            lines.append(f"### Result {i} (score={score:.3f}, {attribution})")
            lines.append(text)
            lines.append("")

        return Response(message="\n".join(lines), break_loop=False)
