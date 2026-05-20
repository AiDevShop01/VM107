"""Phase 44 HARD tool scope: idea_agent MUST NOT call subordinates.

Prevents Idea->Strategy bypass that would skip Coordinator scope enforcement.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/call_subordinate.py via subagents.get_paths()
profile-priority resolution. It raises UnauthorizedToolError before any tool work
happens.
"""
from helpers.tool import Tool, Response
class Delegation(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (
            "Tool 'call_subordinate' is NOT AVAILABLE to idea_agent (hard-scoped "
            "per Phase 47.6 registry projection). Continue your task "
            "without this tool — do NOT retry; it will refuse again. "
            "Use only your allowed tools. Produce your final answer "
            "via the `response` tool."
        )
        return Response(message=msg, break_loop=False)