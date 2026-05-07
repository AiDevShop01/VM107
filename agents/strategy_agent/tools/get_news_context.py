"""Phase 47.2 HARD scope: strategy_agent MUST NOT use trade-context tools.

Trade-context tools are Coordinator-only (Phase 47.2 lock — see
.planning/phases/47.2-trade-context-tooling-wave-3-inserted/47.2-CONTEXT.md
§ Tool Scoping). strategy_agent works on portfolio-level decisions and has
no trade-context need.

Per-profile denial stub overrides the global tools/get_news_context.py via
subagents.get_paths() priority order: agents/<profile>/tools/<name>.py wins
over tools/<name>.py.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class GetNewsContext(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError("strategy_agent", "get_news_context")
