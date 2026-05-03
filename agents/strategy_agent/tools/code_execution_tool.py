"""Phase 44 HARD tool scope: strategy_agent MUST NOT execute code.

Strategy Agent is a pure transformation (Hypothesis -> StrategySpec).
Code execution is reserved for the Coordinator (agent_zero) in Phase 44.
Future Code Agent (Phase 45) will receive an explicit allow.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/code_execution_tool.py via subagents.get_paths()
profile-priority resolution. It raises UnauthorizedToolError before any tool work
happens.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class CodeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError("strategy_agent", "code_execution_tool")
