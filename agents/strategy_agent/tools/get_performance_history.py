"""Phase 47.2 HARD scope: strategy_agent MUST NOT use trade-context tools.

Trade-context tools are Coordinator-only (Phase 47.2 lock — see
.planning/phases/47.2-trade-context-tooling-wave-3-inserted/47.2-CONTEXT.md
§ Tool Scoping). strategy_agent works on portfolio-level decisions and has
no trade-context need.

Per-profile denial stub overrides the global tools/get_performance_history.py
via subagents.get_paths() priority order: agents/<profile>/tools/<name>.py
wins over tools/<name>.py.
"""
from helpers.tool import Tool, Response
class GetPerformanceHistory(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (
            "Tool 'get_performance_history' is NOT AVAILABLE to strategy_agent (hard-scoped "
            "per Phase 47.6 registry projection). Continue your task "
            "without this tool — do NOT retry; it will refuse again. "
            "Use only your allowed tools. Produce your final answer "
            "via the `response` tool."
        )
        return Response(message=msg, break_loop=False)