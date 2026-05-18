"""Phase 48 Plan 06 HARD tool scope: strategy_refinement_critic MUST NOT execute trades.

The Critic evaluates strategy ARTIFACTS — it does not execute trades, place
orders, or interact with broker APIs. Trade execution belongs to live
trading agents downstream of acceptance + governance gates.

This file overrides any global tools/trade_execution_tool.py via
subagents.get_paths() profile-priority resolution. It raises
UnauthorizedToolError before any tool work happens.
"""
from helpers.tool import Tool, Response
from core.agents.tool_scope import UnauthorizedToolError


class TradeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        raise UnauthorizedToolError(
            "strategy_refinement_critic", "trade_execution_tool"
        )
