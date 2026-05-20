"""Phase 44 HARD tool scope: strategy_agent MUST NOT call subordinates.

Strategy Agent is a pure transformation (Hypothesis -> StrategySpec).
Calling subordinates would bypass Coordinator scope enforcement and break
the delegation discipline.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/call_subordinate.py via subagents.get_paths()
profile-priority resolution. It raises UnauthorizedToolError before any tool work
happens.
"""
from helpers.tool import Tool, Response
class Delegation(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (
            "Tool 'call_subordinate' is NOT AVAILABLE to strategy_agent (hard-scoped "
            "per Phase 47.6 registry projection). Continue your task "
            "without this tool — do NOT retry; it will refuse again. "
            "Use only your allowed tools. Produce your final answer "
            "via the `response` tool."
        )
        return Response(message=msg, break_loop=False)