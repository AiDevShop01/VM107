"""Phase 48 deterministic orchestrator policy — SINGLE SOURCE OF TRUTH.

Plan 05 imports from here. Plan 08b imports from here. Plan 06 reads ACCEPT_FLOORS
for the Critic's prompt context. NEVER override at runtime. NEVER redefine in
another refinement_orchestrator/*.py module (test_policy_constants enforces).

CONTEXT § Decision 2: "All policy constants ... live in orchestrator config —
single source of truth, auditable, replayable."

Numeric values are PLANNER-LOCKED (CONTEXT § Decisions 8 + 9 + 10 + Phase 46
ROADMAP). Tightening floors over time is explicitly deferred (Phase 49 may
revisit once realistic distributions exist; V1 stays stable).
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Iteration budget (CONTEXT § Decision 4 + § Boundedness).
# ---------------------------------------------------------------------------

#: Maximum refinement iterations per loop. CONTEXT § Decision 4 — bounded
#: deterministic adjudicator. After this, orchestrator terminates with
#: TerminationReason.MAX_ITERATIONS.
MAX_ITERATIONS: Final[int] = 3


# ---------------------------------------------------------------------------
# Acceptance floor (CONTEXT § Decision 8 + Phase 46 ROADMAP V1 numbers).
# ---------------------------------------------------------------------------

#: Phase 46 ROADMAP V1 acceptance-floor metrics. acceptance_floor.py reads
#: these via dict lookup; the comparison direction (>= for floor, <= for
#: ceiling) is hard-coded in the classifier (max_drawdown is the only
#: "ceiling" metric — exceeding it is the failure).
ACCEPT_FLOORS: Final[dict[str, float | int]] = {
    "sample_size": 200,
    "win_rate": 0.45,
    "max_drawdown": 0.20,
    "profit_factor": 1.2,
}

#: Planner-locked severity policy (CONTEXT § Decision 8 — "Concrete
#: REFINE-vs-REJECT severity policy picked in planning"). A metric breach
#: greater than this threshold (>20% under floor / >20% over ceiling) is
#: HARD_REJECT; at or below is REFINABLE_WEAKNESS.
ACCEPT_FLOOR_BREACH_THRESHOLD: Final[float] = 0.20


# ---------------------------------------------------------------------------
# Hard vetoes (CONTEXT § Decision 9 — catastrophic-only, family-agnostic).
# ---------------------------------------------------------------------------

#: 4 catastrophic-only veto rules. hard_vetoes.py iterates this dict and emits
#: one veto entry per triggered key. Op symbols (">" / "<") describe the
#: FAILURE direction (i.e., metric is veto-tripped when `actual {op} value`).
HARD_VETOES: Final[dict[str, dict[str, float | int | str]]] = {
    "max_drawdown": {"op": ">", "value": 0.35},
    "win_rate": {"op": "<", "value": 0.30},
    "consecutive_losses": {"op": ">", "value": 10},
    "regime_coverage": {"op": "<", "value": 0.20},
}


# ---------------------------------------------------------------------------
# Identity-drift gate (CONTEXT § Decision 10 — anti-drift, tightening ratchet).
# ---------------------------------------------------------------------------

#: iteration_number -> minimum similarity score required vs spec_iter0.
#: Plan 05's identity_scorer compares each new StrategySpec to the iter-0
#: spec; below the iteration's threshold -> orchestrator forces IDENTITY_DRIFT
#: termination (Critic cannot override).
IDENTITY_THRESHOLDS: Final[dict[int, float]] = {
    1: 0.70,
    2: 0.80,
    3: 0.90,
}


# ---------------------------------------------------------------------------
# Budget caps (CONTEXT § Decision 14 — separate LLM vs infrastructure tracks).
# ---------------------------------------------------------------------------

#: LLM USD budget caps (cognition cost). Plan 05's budget gate compares
#: per-iteration ExecutionCost.usd_cost to per_iteration; cumulative loop
#: cost to per_loop. Breach -> TerminationReason.BUDGET_EXCEEDED_*.
BUDGET_CAPS_USD: Final[dict[str, float]] = {
    "per_iteration": 1.50,
    "per_loop": 5.00,
}

#: Wall-time budget caps in milliseconds (infrastructure cost — Backtester
#: dominates). 20 minutes per iteration, 60 minutes per loop.
BUDGET_CAPS_WALL_TIME_MS: Final[dict[str, int]] = {
    "per_iteration": 20 * 60 * 1000,
    "per_loop": 60 * 60 * 1000,
}


__all__ = [
    "MAX_ITERATIONS",
    "ACCEPT_FLOORS",
    "ACCEPT_FLOOR_BREACH_THRESHOLD",
    "HARD_VETOES",
    "IDENTITY_THRESHOLDS",
    "BUDGET_CAPS_USD",
    "BUDGET_CAPS_WALL_TIME_MS",
]
