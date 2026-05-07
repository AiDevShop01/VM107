"""Phase 47.2 HARD scope: idea_agent MUST NOT use trade-context tools.

Trade-context tools are Coordinator-only (Phase 47.2 lock — see
.planning/phases/47.2-trade-context-tooling-wave-3-inserted/47.2-CONTEXT.md
§ Tool Scoping). idea_agent operates strategically and has no trade-context
need.

Per-profile denial stub overrides the global tools/get_primitives.py via
subagents.get_paths() priority order: agents/<profile>/tools/<name>.py wins
over tools/<name>.py.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class GetPrimitives(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError("idea_agent", "get_primitives")
