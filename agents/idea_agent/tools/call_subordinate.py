"""Phase 44 HARD tool scope: idea_agent MUST NOT call subordinates.

Prevents Idea->Strategy bypass that would skip Coordinator scope enforcement.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/call_subordinate.py via subagents.get_paths()
profile-priority resolution. It raises UnauthorizedToolError before any tool work
happens.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class Delegation(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError("idea_agent", "call_subordinate")
