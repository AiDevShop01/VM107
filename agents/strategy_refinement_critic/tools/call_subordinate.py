"""Phase 48 Plan 06 HARD tool scope: strategy_refinement_critic MUST NOT call subordinates.

The Critic is a transformation-pure evaluator. Calling subordinates would
bypass Coordinator scope enforcement and break the cognition-policy
separation lock (CONTEXT § Decision 1 + § Anti-Patterns).

This file overrides the global tools/call_subordinate.py via
subagents.get_paths() profile-priority resolution. It raises
UnauthorizedToolError before any tool work happens.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class Delegation(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError(
            "strategy_refinement_critic", "call_subordinate"
        )
