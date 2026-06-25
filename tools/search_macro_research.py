"""Phase 92 Plan 05 — search_macro_research tool.

Cross-VM tool: VM107 → VM101 POST /api/v1/research/search → Qdrant + Postgres.

Implements 92-RESEARCH.md §"search_macro_research tool implementation skeleton"
(lines 681-708). URL is env-driven via VM101_RESEARCH_SEARCH_URL with NO
fallback default (CLAUDE.md `feedback_env_driven_no_fallbacks` lock).

Contract: fingpt_core.contracts.research.SearchMacroResearchRequest →
SearchMacroResearchResponse. The Plan-5 Phase 89 macro_investigator flip
(denied→allowed) makes this tool callable from indicator-scoped Q&A.

Architecture:
- ``SearchMacroResearchTool`` is the agent-callable tool (inherits ``Tool`` from
  helpers.tool so Agent Zero dispatch resolves it). Instantiation requires the
  Tool framework positional args (agent, name, method, args, message, loop_data).
- ``search_macro_research_call`` is a thin async function exposing the same
  contract for tests + direct Python callers (no Agent Zero context required).
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

# Lazy Tool import — host-shell test environments may not have the full
# Agent Zero stack loaded; the test surface (search_macro_research_call) is
# framework-free so tests don't need to instantiate the Tool subclass.
try:
    from helpers.tool import Response, Tool  # type: ignore
except Exception:  # pragma: no cover

    class Tool:  # type: ignore[no-redef]
        """Bare-class shim so host-shell tests can import this module
        without the Agent Zero core."""

        def __init__(self, *_a, **_k) -> None:
            pass

    class Response:  # type: ignore[no-redef]
        def __init__(self, message: str = "", break_loop: bool = False) -> None:
            self.message = message
            self.break_loop = break_loop


async def search_macro_research_call(
    query: str,
    indicator_id: Optional[str] = None,
    tier_filter: Optional[list[int]] = None,
    asset_id: Optional[str] = None,
    top_k: int = 5,
) -> Any:
    """Framework-free async entry point.

    Returns either a fingpt_core SearchMacroResearchResponse (when fingpt_core
    is importable) or the raw decoded JSON dict.

    Raises RuntimeError if VM101_RESEARCH_SEARCH_URL is unset
    (env-driven-no-fallbacks lock).
    """
    url = os.environ.get("VM101_RESEARCH_SEARCH_URL")
    if not url:
        raise RuntimeError(
            "VM101_RESEARCH_SEARCH_URL not set — Phase 92 Plan 05 tool "
            "requires env-driven URL (no fallback default per "
            "CLAUDE.md feedback_env_driven_no_fallbacks)"
        )

    filters: dict[str, Any] = {"type": "research_document"}
    if indicator_id:
        filters["linked_indicator"] = indicator_id
    if tier_filter:
        filters["tier"] = list(tier_filter)
    if asset_id:
        filters["asset_id"] = asset_id

    payload = {"query": query, "top_k": int(top_k), "filters": filters}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    data = resp.json()
    # Best-effort Pydantic coercion if fingpt_core is on PYTHONPATH.
    try:
        from fingpt_core.contracts.research import (  # type: ignore
            SearchMacroResearchResponse,
        )

        return SearchMacroResearchResponse.model_validate(data)
    except Exception:
        return data


class SearchMacroResearchTool(Tool):
    """Indicator-aware semantic search over macro research substrate.

    Backed by VM101 ``POST /api/v1/research/search``. Agent-callable surface
    that wraps :func:`search_macro_research_call`.
    """

    name = "search_macro_research"
    description = (
        "Semantic search across macro research documents (Tier 1 official + "
        "Tier 3 academic). Filter by indicator_id, tier_filter, asset_id."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Tool framework instantiates with (agent, name, method, args, message,
        # loop_data); tests can instantiate as `SearchMacroResearchTool()` and
        # use ``execute`` directly because we route to the framework-free helper.
        if args or kwargs:
            try:
                super().__init__(*args, **kwargs)
            except TypeError:
                pass

    async def execute(
        self,
        query: str = "",
        indicator_id: Optional[str] = None,
        tier_filter: Optional[list[int]] = None,
        asset_id: Optional[str] = None,
        top_k: int = 5,
        **_kwargs: Any,
    ) -> Any:
        if not query.strip():
            try:
                return Response(
                    message="Error: search_macro_research requires a non-empty 'query' arg.",
                    break_loop=False,
                )
            except Exception:
                return {
                    "error": "search_macro_research requires a non-empty 'query' arg"
                }

        return await search_macro_research_call(
            query=query,
            indicator_id=indicator_id,
            tier_filter=tier_filter,
            asset_id=asset_id,
            top_k=int(top_k),
        )
