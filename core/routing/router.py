"""
ModelRouter — deterministic, policy-driven LLM model selection engine.

Implements the 8-step routing pipeline locked in CONTEXT.md:
    1. Load context        (task + goal + brain via AgentRunner.execution_context)
    2. Budget gate         (HARD STOP if goal.spent_today >= goal.max_budget)
    3. Select candidates   (affinity_map[agent_id or 'default'][task_type or 'default'])
    4. Brain-mode filter   (hard filter for stabilization; soft re-rank for exploration/exploitation)
    5. Latency filter      (drop models exceeding context.latency_sla_ms)
    6. Peak/off-peak       (peak: hard tier-shift; off-peak: quality_weight boost)
    7. Build fallback chain ({primary, fallback: [secondary, local]})
    8. Log decision        (mandatory structured JSON per call)

Anti-patterns (NEVER):
    - LLM-driven model selection (router is deterministic, always)
    - Per-call MongoDB queries (use Redis aggregates)
    - Modifying agent.py or models.py (extension-only)
    - Hard filter in exploration mode (kills discovery)
    - Soft filter in stabilization mode (defeats safety)

Implementation plan:
    - Steps 1-8 stubs: Plan 02 (affinity + scoring), Plan 03 (budget gate),
      Plan 04 (alert pipeline), Plan 05 (full pipeline + hooks wiring)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.routing.schemas import RouterContext, RoutingDecision

if TYPE_CHECKING:
    from core.routing.affinity import AffinityMap
    from core.routing.alert_pipeline import AlertPipeline
    from core.routing.budget_gate import BudgetGate
    from core.routing.peak_schedule import PeakSchedule

logger = logging.getLogger("router")


class ModelRouter:
    """
    Deterministic LLM model router.

    Selects the optimal model for each LLM call based on:
    - Goal/task affinity configuration (YAML)
    - Hard budget enforcement (Redis aggregate cache)
    - Brain-mode filters (reads Brain, never writes it)
    - Time-of-day peak/off-peak schedule (YAML)
    - Latency SLA constraints

    All public methods raise NotImplementedError until Wave 1 plans implement them.
    Imports succeed immediately so Wave 1 test files can reference class/method names.

    Constructor args:
        affinity_map: Loaded affinity YAML (agent_id -> task_type -> model chain)
        budget_gate: Redis-backed budget check + breach handler
        alert_pipeline: Multi-sink alert fan-out (stdout + MongoDB + Brain + external)
        peak_schedule: Timezone-aware peak window detector
        mode_weights: Dict of {mode: {quality: float, cost: float, latency: float}}
        model_catalog: Dict of {model_id: {tier, quality_score, latency_ms}}
        signal_accumulator: Phase 42 SignalAccumulator for cost_pressure signals
        mongo_client: MongoDB client for decision log writes
        logger: Optional logger override (defaults to module logger)
    """

    def __init__(
        self,
        affinity_map: "AffinityMap",
        budget_gate: "BudgetGate",
        alert_pipeline: "AlertPipeline",
        peak_schedule: "PeakSchedule",
        mode_weights: dict,
        model_catalog: dict,
        signal_accumulator: Any,
        mongo_client: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self.affinity_map = affinity_map
        self.budget_gate = budget_gate
        self.alert_pipeline = alert_pipeline
        self.peak_schedule = peak_schedule
        self.mode_weights = mode_weights
        self.model_catalog = model_catalog
        self.signal_accumulator = signal_accumulator
        self.mongo_client = mongo_client
        self._logger = logger or globals()["logger"]

    @classmethod
    def from_yaml(cls, path: str) -> "ModelRouter":
        """
        Construct ModelRouter from a model_routing.yaml config file.

        Instantiates AffinityMap, BudgetGate, AlertPipeline, PeakSchedule with
        config-driven defaults. For production use via the before_main_llm_call
        extension (lazy-init pattern: agent.get_data/set_data "model_router").

        Args:
            path: Absolute path to model_routing.yaml

        Raises:
            NotImplementedError: Until Plan 02 implements full construction.
        """
        raise NotImplementedError("Phase 43 Plan 02: ModelRouter.from_yaml() pending")

    def decide(self, ctx: RouterContext) -> RoutingDecision:
        """
        Run the 8-step routing pipeline and return a model selection decision.

        This is the primary entry point called by the before_main_llm_call extension.
        The returned RoutingDecision is stored in loop_data.params_temporary and
        applied by the chat_model_call_before extension via call_data["model"].

        Args:
            ctx: Immutable routing context (task_id, goal_id, agent_id, task_type,
                 priority, latency_sla_ms, brain_context)

        Returns:
            RoutingDecision with primary + fallback chain and structured reason list.

        Raises:
            NotImplementedError: Until Plan 05 implements full pipeline.
        """
        raise NotImplementedError("Phase 43 Plan 05: ModelRouter.decide() pending")

    # -----------------------------------------------------------------------
    # Private pipeline steps (8 steps — each owned by a specific Wave 1 plan)
    # -----------------------------------------------------------------------

    def _load_context(self, ctx: RouterContext) -> dict:
        """
        Step 1: Extract goal + brain context for downstream steps.

        Reads: goal.max_budget_usd, goal.enqueue_blocked, brain_context.mode,
               brain_context.resource_policy.

        Raises:
            NotImplementedError: Until Plan 05 implements context loading.
        """
        raise NotImplementedError("Phase 43 Plan 05: _load_context() pending")

    def _budget_gate(self, ctx: RouterContext, goal_data: dict) -> tuple[bool, str]:
        """
        Step 2: Hard budget gate — check Redis aggregate for goal spend.

        Returns (allowed, reason). If not allowed, caller returns local-only chain
        immediately without running steps 3-7.

        Raises:
            NotImplementedError: Until Plan 03 implements budget gate.
        """
        raise NotImplementedError("Phase 43 Plan 03: _budget_gate() pending")

    def _select_candidates(self, ctx: RouterContext) -> list[dict]:
        """
        Step 3: Select model candidates from affinity map.

        Lookup: affinity[agent_id][task_type] -> affinity[agent_id][default] -> affinity[default][default]
        Each fallback path logged in reason[].

        Returns list of candidate dicts with {model_id, tier, quality_score, latency_ms}.

        Raises:
            NotImplementedError: Until Plan 02 implements affinity lookup.
        """
        raise NotImplementedError("Phase 43 Plan 02: _select_candidates() pending")

    def _apply_brain_filter(self, candidates: list[dict], brain_context: dict) -> list[dict]:
        """
        Step 4: Apply brain-mode filter to candidate set.

        stabilization: HARD FILTER — drop 'expensive' and 'unsafe' tier models.
        exploration:   SOFT PREFERENCE — retain all, bias quality weight up.
        exploitation:  SOFT PREFERENCE — retain all, bias cost/latency weight.

        Router READS brain.mode. Router NEVER writes Brain state.

        Raises:
            NotImplementedError: Until Plan 05 implements brain filter.
        """
        raise NotImplementedError("Phase 43 Plan 05: _apply_brain_filter() pending")

    def _apply_latency_filter(self, candidates: list[dict], latency_sla_ms: int) -> list[dict]:
        """
        Step 5: Drop models exceeding context.latency_sla_ms.

        Local tier is never dropped regardless of latency (guarantees fallback).

        Raises:
            NotImplementedError: Until Plan 02 implements latency filter.
        """
        raise NotImplementedError("Phase 43 Plan 02: _apply_latency_filter() pending")

    def _apply_peak_modifier(self, candidates: list[dict], peak: bool, mode: str) -> list[dict]:
        """
        Step 6: Apply peak/off-peak modifier to candidate scores.

        peak=True:  HARD tier-shift — candidates restricted to secondary tier (expensive
                    primary models dropped). Cost ceiling guaranteed during peak hours.
        peak=False: SOFT quality boost — quality_weight *= 1.2-1.3 to favor better models
                    when cost pressure is lower.

        Peak MUST preserve full primary->secondary->local chain even under cost pressure.

        Raises:
            NotImplementedError: Until Plan 02 implements peak modifier.
        """
        raise NotImplementedError("Phase 43 Plan 02: _apply_peak_modifier() pending")

    def _build_fallback_chain(self, candidates: list[dict], peak: bool) -> dict:
        """
        Step 7: Build {primary, fallback: [secondary, local]} chain.

        Local tier always present in fallback (guarantees agent can always respond).
        Chain integrity preserved even in peak mode.

        Returns: {"primary": model_id, "fallback": [secondary_id, local_id]}

        Raises:
            NotImplementedError: Until Plan 05 implements chain builder.
        """
        raise NotImplementedError("Phase 43 Plan 05: _build_fallback_chain() pending")

    def _log_decision(self, decision: RoutingDecision) -> None:
        """
        Step 8: Write mandatory structured decision log to MongoDB + stdout.

        Mandatory fields (8): task_id, goal_id, agent_id, task_type, selected_model,
        fallback[], reason[], decision_time_ms.

        MongoDB target: router_decisions collection (created by migration 005).

        Raises:
            NotImplementedError: Until Plan 05 implements decision logging.
        """
        raise NotImplementedError("Phase 43 Plan 05: _log_decision() pending")
