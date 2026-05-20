"""Phase 48 Plan 06 HARD tool scope: strategy_refinement_critic MUST NOT execute code.

The Critic evaluates artifacts only. Code execution is reserved for the
Coordinator (agent_zero) and the Code Agent (which receives an explicit
allow at its own profile boundary).

This file overrides the global tools/code_execution_tool.py via
subagents.get_paths() profile-priority resolution. It raises
UnauthorizedToolError before any tool work happens.
"""
from helpers.tool import Tool, Response
class CodeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (

            "Tool 'code_execution_tool' is NOT AVAILABLE to strategy_refinement_critic (hard-scoped "

            "per Phase 47.6 registry projection). Continue your task "

            "without this tool — do NOT retry; it will refuse again. "

            "Use only your allowed tools. Produce your final answer "

            "via the `response` tool."

        )

        return Response(message=msg, break_loop=False)
