"""Phase 48 Plan 06 — per-profile denial stubs for strategy_refinement_critic.

The 3 sensitive tools (call_subordinate, code_execution_tool, trade_execution_tool)
are HARD-blocked at the agent runtime layer via these stubs. They override the
global tools/<tool>.py via subagents.get_paths() profile-priority resolution.

CONTEXT § Decision 1 — Critic evaluates artifacts only.
"""
