"""Phase 48 Plan 06 HARD tool scope: strategy_refinement_critic MUST NOT execute trades.

The Critic evaluates strategy ARTIFACTS — it does not execute trades, place
orders, or interact with broker APIs. Trade execution belongs to live
trading agents downstream of acceptance + governance gates.

This file overrides any global tools/trade_execution_tool.py via
subagents.get_paths() profile-priority resolution. It raises
UnauthorizedToolError before any tool work happens.
"""
from helpers.tool import Tool, Response
class TradeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        msg = (

            "Tool 'trade_execution_tool' is NOT AVAILABLE to strategy_refinement_critic (hard-scoped "

            "per Phase 47.6 registry projection). Continue your task "

            "without this tool — do NOT retry; it will refuse again. "

            "Use only your allowed tools. Produce your final answer "

            "via the `response` tool."

        )

        return Response(message=msg, break_loop=False)
