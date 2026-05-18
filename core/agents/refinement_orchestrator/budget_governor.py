"""Phase 48 Plan 48-05 — refinement-loop budget governor.

REQ-48-D14. CONTEXT § Decision 14 LOCKED:
  "Deterministic Python caps at BOTH levels. Circuit breakers, not soft
   suggestions."

Architecture (CONTEXT § Decision 14):
  Phase 38 ExecutionBoundary -> per-agent caps (different layer)
  Phase 48 BudgetGovernor (this module) -> per-iteration + per-loop refinement caps
  TWO distinct termination reasons:
    BUDGET_EXCEEDED_ITERATION  (per-iteration cap hit)
    BUDGET_EXCEEDED_LOOP       (per-loop aggregate cap hit)

Pure Python. No I/O. No LLM. No registry. The orchestrator (Plan 08b) calls:
  - ``BudgetGovernor(state)`` once at iteration-N entry.
  - ``track_cost(cost)`` after each stage (Strategy, Code, Build, Backtest, Critic).
  - ``check_iteration_cap()`` after iteration's cost batch.
  - ``check_loop_cap()`` at loop level.
  - ``preflight(estimated_iteration_floor_usd)`` BEFORE next iteration starts.
  - ``reset_iteration_tally()`` at iteration boundary (loop counters preserved).

Critic-budget-blind invariant (CONTEXT § Anti-Patterns): this module MUST NOT
import ``run_critic`` and MUST NOT thread budget state into Critic prompt
payloads. test_critic_budget_blind enforces both.

Category separation (CONTEXT § Decision 14): LLM cognition USD and
INFRASTRUCTURE wall-time USD are tracked into DISTINCT keys for telemetry
(Phase 56 emit downstream surfaces per-category breakdown). For cap
comparison the two are SUMMED (single dollar budget per scope, regardless
of where it was spent).
"""
from __future__ import annotations

from typing import Any

from core.agents.refinement_orchestrator.policy_constants import (
    BUDGET_CAPS_USD,
    BUDGET_CAPS_WALL_TIME_MS,
)
from core.contracts.exceptions import LoopBudgetExceeded
from core.contracts.schemas import ExecutionCost, RefinementLoopState

# ---------------------------------------------------------------------------
# Canonical budget_snapshot key set. Locked here so persistence (Plan 03's
# update_loop_state) and replay (Plan 09) agree on the schema.
# ---------------------------------------------------------------------------

_INITIAL_SNAPSHOT: dict[str, Any] = {
    # totals (USD, ALL categories summed)
    "iteration_usd": 0.0,
    "loop_total_usd": 0.0,
    # category-separated USD (CONTEXT § Decision 14)
    "iteration_llm_usd": 0.0,
    "iteration_infrastructure_usd": 0.0,
    "loop_total_llm_usd": 0.0,
    "loop_total_infrastructure_usd": 0.0,
    # wall-time (ms)
    "iteration_wall_ms": 0,
    "loop_total_wall_ms": 0,
    # tokens (counted across ALL costs; only LLM costs should carry tokens>0
    # but the governor doesn't enforce that — ExecutionCost.tokens fields are
    # >=0 Pydantic constraints).
    "iteration_tokens": 0,
    "loop_total_tokens": 0,
}


def _bootstrap_snapshot(existing: dict[str, Any] | None) -> dict[str, Any]:
    """Return a snapshot dict that is guaranteed to carry every required key.

    Resuming from a checkpoint: ``existing`` may be a partial snapshot left by
    a prior process. Missing keys default to the zero baseline; existing
    values are preserved.
    """
    snap = dict(_INITIAL_SNAPSHOT)
    if existing:
        for key, value in existing.items():
            snap[key] = value
    return snap


class BudgetGovernor:
    """Deterministic refinement-loop budget gate.

    Reads ``state.budget_snapshot`` at construction; from that point the
    Governor owns its own counters in-memory. The orchestrator persists the
    snapshot back into ``RefinementLoopState`` between iterations via
    ``update_loop_state`` so the loop is resumable.

    No I/O. No Mongo. No LLM. No registry. test_orchestrator_purity walks
    every refinement_orchestrator/*.py and asserts.
    """

    def __init__(self, state: RefinementLoopState) -> None:
        self._budget_snapshot: dict[str, Any] = _bootstrap_snapshot(state.budget_snapshot)

    # -----------------------------------------------------------------------
    # Telemetry surface — read-only snapshot view for callers.
    # -----------------------------------------------------------------------

    @property
    def budget_snapshot(self) -> dict[str, Any]:
        """The live in-memory snapshot dict.

        Returned by-reference for performance; the orchestrator never mutates
        it directly (writes flow through ``track_cost`` / ``reset_iteration_tally``).
        """
        return self._budget_snapshot

    # -----------------------------------------------------------------------
    # Mutation: track_cost + reset_iteration_tally.
    # -----------------------------------------------------------------------

    def track_cost(self, cost: ExecutionCost) -> None:
        """Accumulate one ExecutionCost into the iteration + loop tallies.

        Args:
            cost: per-stage cost emitted by Strategy / Code / Build /
                Backtest / Critic typed wrappers (Plan 48-01).
        """
        snap = self._budget_snapshot
        usd = float(cost.usd_cost)
        wall_ms = int(cost.wall_time_ms)
        tokens = int(cost.tokens_in) + int(cost.tokens_out)

        # Totals (aggregated regardless of category — single dollar budget).
        snap["iteration_usd"] += usd
        snap["loop_total_usd"] += usd
        snap["iteration_wall_ms"] += wall_ms
        snap["loop_total_wall_ms"] += wall_ms
        snap["iteration_tokens"] += tokens
        snap["loop_total_tokens"] += tokens

        # Category-segmented USD.
        if cost.category == "LLM":
            snap["iteration_llm_usd"] += usd
            snap["loop_total_llm_usd"] += usd
        elif cost.category == "INFRASTRUCTURE":
            snap["iteration_infrastructure_usd"] += usd
            snap["loop_total_infrastructure_usd"] += usd
        # ExecutionCost.category is Literal["LLM", "INFRASTRUCTURE"] -- Pydantic
        # forbids anything else, so an else branch is unreachable.

    def reset_iteration_tally(self) -> None:
        """Zero the iteration-scope counters; preserve loop-scope counters.

        Orchestrator calls this between iterations. Loop counters keep
        accumulating so ``check_loop_cap`` and ``preflight`` see the true
        aggregate.
        """
        snap = self._budget_snapshot
        snap["iteration_usd"] = 0.0
        snap["iteration_llm_usd"] = 0.0
        snap["iteration_infrastructure_usd"] = 0.0
        snap["iteration_wall_ms"] = 0
        snap["iteration_tokens"] = 0

    # -----------------------------------------------------------------------
    # Cap checks.
    # -----------------------------------------------------------------------

    def check_iteration_cap(self) -> None:
        """Raise ``LoopBudgetExceeded(scope=ITERATION)`` if iteration over cap.

        Two cap dimensions enforced:
          * USD: ``iteration_usd > BUDGET_CAPS_USD['per_iteration']`` (1.50)
          * Wall-time: ``iteration_wall_ms > BUDGET_CAPS_WALL_TIME_MS['per_iteration']``
            (20 minutes)

        Either trip raises with scope=ITERATION; consumed_usd is the
        iteration USD (USD is the canonical currency the exception reports).
        """
        snap = self._budget_snapshot
        cap_usd = BUDGET_CAPS_USD["per_iteration"]
        cap_wall_ms = BUDGET_CAPS_WALL_TIME_MS["per_iteration"]

        if snap["iteration_usd"] > cap_usd:
            raise LoopBudgetExceeded(
                scope="ITERATION",
                consumed_usd=float(snap["iteration_usd"]),
                cap_usd=float(cap_usd),
            )
        if snap["iteration_wall_ms"] > cap_wall_ms:
            raise LoopBudgetExceeded(
                scope="ITERATION",
                consumed_usd=float(snap["iteration_usd"]),
                cap_usd=float(cap_usd),
            )
        return None

    def check_loop_cap(self) -> None:
        """Raise ``LoopBudgetExceeded(scope=LOOP)`` if loop aggregate over cap.

        Two cap dimensions enforced:
          * USD: ``loop_total_usd > BUDGET_CAPS_USD['per_loop']`` (5.00)
          * Wall-time: ``loop_total_wall_ms > BUDGET_CAPS_WALL_TIME_MS['per_loop']``
            (60 minutes)
        """
        snap = self._budget_snapshot
        cap_usd = BUDGET_CAPS_USD["per_loop"]
        cap_wall_ms = BUDGET_CAPS_WALL_TIME_MS["per_loop"]

        if snap["loop_total_usd"] > cap_usd:
            raise LoopBudgetExceeded(
                scope="LOOP",
                consumed_usd=float(snap["loop_total_usd"]),
                cap_usd=float(cap_usd),
            )
        if snap["loop_total_wall_ms"] > cap_wall_ms:
            raise LoopBudgetExceeded(
                scope="LOOP",
                consumed_usd=float(snap["loop_total_usd"]),
                cap_usd=float(cap_usd),
            )
        return None

    def preflight(self, estimated_iteration_floor_usd: float) -> bool:
        """Return True iff remaining loop budget covers the next iteration's floor.

        CONTEXT § Decision 14 (NO GRACE ITERATION):
          "remaining_loop_budget < estimated_iteration_floor -> terminate
           immediately (no grace iteration)."

        Args:
            estimated_iteration_floor_usd: lowest plausible USD cost for the
                next iteration (orchestrator picks the conservative floor,
                typically equal to BUDGET_CAPS_USD['per_iteration']).

        Returns:
            True iff remaining >= floor (loop can run another iteration).
            False otherwise (orchestrator MUST terminate with
            ``TerminationReason.BUDGET_EXCEEDED_LOOP``).
        """
        cap_usd = BUDGET_CAPS_USD["per_loop"]
        remaining = cap_usd - float(self._budget_snapshot["loop_total_usd"])
        return remaining >= float(estimated_iteration_floor_usd)


__all__ = ["BudgetGovernor"]
