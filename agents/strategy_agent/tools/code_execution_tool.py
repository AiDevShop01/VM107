"""Phase 44 HARD tool scope: strategy_agent MUST NOT execute code.

Strategy Agent is a pure transformation (Hypothesis -> StrategySpec).
Code execution is reserved for the Coordinator (agent_zero) in Phase 44.
Future Code Agent (Phase 45) will receive an explicit allow.
See CONTEXT.md § Tool Scoping (HYBRID).

This file overrides the global tools/code_execution_tool.py via subagents.get_paths()
profile-priority resolution.

Behavior (revised 2026-05-20 after UAT-40.2-02 finding AZ02):
Returns a soft refusal Response (not raise UnauthorizedToolError) so the
agent loop can recover. The LLM sees the refusal message on the next
iteration and self-corrects to producing the StrategySpec without code
execution. Raising crashed the whole subordinate call because
agent.py:509 monologue() doesn't catch and recover — the user got a
traceback instead of a final StrategySpec. Prompt-level "don't call this
tool" instructions lose to the visible tool inventory; only making the
call itself harmlessly recoverable actually solves it.
"""
from helpers.tool import Tool, Response


_REFUSAL_MESSAGE = (
    "Tool 'code_execution_tool' is NOT AVAILABLE to the strategy_agent. "
    "Code execution is hard-scoped to a future Code Agent (Phase 45) that "
    "has not shipped yet. You are the strategy_agent — your job is to emit "
    "a declarative StrategySpec JSON via the `response` tool, NOT to "
    "execute code. Continue without code execution: produce the best "
    "StrategySpec you can from the available read-only tools "
    "(search_knowledge, document_query, VM data clients). If the request "
    "fundamentally requires code execution, return a StrategySpec with a "
    "final rules entry of the form 'NOTE: code execution / backtest "
    "deferred — Phase 45 Code Agent not yet shipped'. Do NOT retry this "
    "tool — it will refuse again."
)


class CodeExecution(Tool):
    async def execute(self, **kwargs) -> Response:
        return Response(message=_REFUSAL_MESSAGE, break_loop=False)
