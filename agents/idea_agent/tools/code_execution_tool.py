"""Phase 44 HARD tool scope: idea_agent MUST NOT execute code.

Code execution is reserved for the Coordinator (agent_zero) in Phase 44.
Future Code Agent (Phase 45) will receive an explicit allow.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/code_execution_tool.py via subagents.get_paths()
profile-priority resolution. It raises UnauthorizedToolError before any tool work
happens.
"""
from helpers.tool import Tool, Response
class CodeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (
            "Tool 'code_execution_tool' is NOT AVAILABLE to idea_agent (hard-scoped "
            "per Phase 47.6 registry projection). Continue your task "
            "without this tool — do NOT retry; it will refuse again. "
            "Use only your allowed tools. Produce your final answer "
            "via the `response` tool."
        )
        return Response(message=msg, break_loop=False)