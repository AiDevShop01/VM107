"""Phase 48 Plan 06 — strategy_refinement_critic Agent Zero profile.

Bounded refinement evaluator. Reads strategy artifacts (StrategySpec +
CodeModule + BuildReport + BacktestResult) and emits a CriticVerdict
(ACCEPT | REFINE | REJECT). Transformation-pure: never rewrites artifacts.

CONTEXT § Decision 1 + § Anti-Patterns:
  - Profile name MUST be 'strategy_refinement_critic' (NEVER 'critic_agent')
  - One profile + per-family SKILL.md overlays (Phase 60 pattern)
  - Critic evaluates artifacts; orchestrator governs the loop
  - Critic NEVER sees budget state (4-guard invariant from Plan 05)
"""
