"""Phase 96 Plan 11 — HTTP shim for GraphSearchTool.find_country_subgraph.

Exposes ``POST /api/world/tools/graph_search/find_country_subgraph``. Wraps
the existing ``GraphSearchTool.find_country_subgraph(iso_alpha2, depth)``
template and returns ``{"nodes": [...], "edges": [...]}``.

VM100 country_subgraph resolver POSTs here. The tool itself lives in
``/a0/tools/graph/graph_search_tool.py`` (Plan 96-11). Without this HTTP
wrapper the tool is unreachable from the VM100 resolver and the
KNOWLEDGE_GRAPH tab degrades to UNAVAILABLE.

Auth: open service-to-service RPC (VM100 carries no API key for VM107).
"""
from __future__ import annotations

import logging

from helpers.api import ApiHandler, Request, Response

log = logging.getLogger(__name__)


class FindCountrySubgraph(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return False

    async def process(self, input: dict, request: Request) -> dict | Response:
        iso = (input or {}).get("iso_alpha2") or (input or {}).get("iso")
        depth_raw = (input or {}).get("depth", 1)

        if not iso or not isinstance(iso, str) or len(iso) != 2:
            return Response(
                '{"error": "iso_alpha2 (2-letter) required"}',
                status=400,
                mimetype="application/json",
            )
        iso = iso.upper()

        try:
            depth = int(depth_raw)
        except (TypeError, ValueError):
            return Response(
                '{"error": "depth must be int 1..3"}',
                status=400,
                mimetype="application/json",
            )

        try:
            # Bypass parent Tool.__init__ (needs agent/name/method/args/etc.
            # — Phase 41 agent-loop concerns that don't apply to a one-shot
            # template invoke via HTTP RPC). Same pattern Plan 96-11 tests
            # use. Wire neo4j_driver from env so the Cypher template can run.
            import os
            from neo4j import GraphDatabase
            from tools.graph.graph_search_tool import GraphSearchTool

            tool = GraphSearchTool.__new__(GraphSearchTool)
            tool.neo4j_driver = GraphDatabase.driver(
                os.environ["NEO4J_URI"],
                auth=(
                    os.environ.get("NEO4J_USER", "neo4j"),
                    os.environ["NEO4J_PASSWORD"],
                ),
            )
            result = tool.find_country_subgraph(iso, depth=depth)
            return {
                "iso_alpha2": iso,
                "depth": depth,
                "nodes": result.get("nodes", []),
                "edges": result.get("edges", []),
            }
        except ValueError as exc:
            return Response(
                f'{{"error": "{exc}"}}',
                status=400,
                mimetype="application/json",
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft surface for VM100
            log.exception(
                "world.country_subgraph.tool_failed",
                extra={"iso": iso, "depth": depth, "exc_type": exc.__class__.__name__},
            )
            return Response(
                f'{{"error": "tool failed: {exc.__class__.__name__}"}}',
                status=500,
                mimetype="application/json",
            )
