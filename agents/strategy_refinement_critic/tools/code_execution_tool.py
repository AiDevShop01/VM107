"""Phase 48 Plan 06 HARD tool scope: strategy_refinement_critic MUST NOT execute code.

The Critic evaluates artifacts only. Code execution is reserved for the
Coordinator (agent_zero) and the Code Agent (which receives an explicit
allow at its own profile boundary).

This file overrides the global tools/code_execution_tool.py via
subagents.get_paths() profile-priority resolution. It raises
UnauthorizedToolError before any tool work happens.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class CodeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError(
            "strategy_refinement_critic", "code_execution_tool"
        )
