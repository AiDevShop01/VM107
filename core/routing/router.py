"""
ModelRouter — deterministic 8-step routing pipeline.

CONTEXT.md locked order:
  1. Load context  (RouterContext from caller)
  2. Budget gate   (HARD STOP) — force_local on breach
  3. Select candidates from affinity map
  4. Brain-mode filter (hard for stabilization, soft for exploration/exploitation)
  5. Latency filter (drop models > ctx.latency_sla_ms)
  6. Peak/off-peak modifier (hard tier-shift in peak; soft quality boost off-peak)
  7. Build {primary, fallback: [secondary, local]} chain
  8. Log decision (mandatory; write to MongoDB router_decisions + stdout)

Anti-patterns (NEVER):
    - LLM-driven model selection (router is deterministic, always)
    - Per-call MongoDB queries (use Redis aggregates)
    - Modifying agent.py or models.py (extension-only)
    - Hard filter in exploration mode (kills discovery)
    - Soft filter in stabilization mode (defeats safety)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.routing.schemas import RouterContext, RoutingDecision
from core.routing import scoring as _scoring

if TYPE_CHECKING:
    from core.routing.affinity import AffinityMap
    from core.routing.alert_pipeline import AlertPipeline
    from core.routing.budget_gate import BudgetGate
    from core.routing.peak_schedule import PeakSchedule

logger = logging.getLogger("router.model_router")


class ModelRouter:
    """
    Deterministic LLM model router.

    Selects the optimal model for each LLM call based on:
    - Goal/task affinity configuration (YAML)
    - Hard budget enforcement (Redis aggregate cache)
    - Brain-mode filters (reads Brain, never writes it)
    - Time-of-day peak/off-peak schedule (YAML)
    - Latency SLA constraints

    Constructor args:
        affinity:        Loaded AffinityMap (agent_id -> task_type -> model chain)
        budget_gate:     Redis-backed budget check + breach handler
        alert_pipeline:  Multi-sink alert fan-out (stdout + MongoDB + Brain + external)
        peak_schedule:   Timezone-aware peak window detector
        mongo_client:    MongoDB client for decision log writes (optional; degrades gracefully)
        logger:          Optional logger override (defaults to module logger)
    """

    def __init__(
        self,
        affinity: "AffinityMap",
        budget_gate: "BudgetGate",
        alert_pipeline: "AlertPipeline",
        peak_schedule: "PeakSchedule",
        mongo_client: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.affinity = affinity
        self.budget_gate = budget_gate
        self.alert_pipeline = alert_pipeline
        self.peak_schedule = peak_schedule
        self.mongo = mongo_client
        self.log = logger or globals()["logger"]

    @classmethod
    def from_yaml(
        cls,
        path: str,
        *,
        redis_client: Any,
        mongo_client: Any,
        signal_accumulator: Any,
        external_notifier: Any = None,
        logger: logging.Logger | None = None,
    ) -> "ModelRouter":
        """
        Construct ModelRouter from a model_routing.yaml config file.

        Instantiates AffinityMap, BudgetGate, AlertPipeline, PeakSchedule with
        config-driven defaults. For production use via the before_main_llm_call
        extension (lazy-init pattern: agent.get_data/set_data "model_router").

        IMPORTANT: budget_caps from affinity is injected into BudgetGate so that
        BudgetGate.get_agent_type_aggregate / get_system_aggregate return the
        correct max_usd from the YAML config (Plan 03 contract).

        Args:
            path:               Absolute path to model_routing.yaml
            redis_client:       Synchronous redis-py client
            mongo_client:       pymongo MongoClient
            signal_accumulator: Phase 42 SignalAccumulator for cost_pressure signals
            external_notifier:  Optional ExternalNotifier stub (Phase 44+ for Slack etc.)
            logger:             Optional logger override
        """
        from core.routing.affinity import AffinityMap
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule

        affinity = AffinityMap.from_yaml(path)
        # Pass affinity.budget_caps so BudgetGate aggregate getters return correct max_usd
        budget_gate = BudgetGate(
            redis_client,
            mongo_client,
            logger,
            budget_caps=affinity.budget_caps,
        )
        alert_pipeline = AlertPipeline(
            mongo_client,
            signal_accumulator,
            external_notifier,
            logger,
        )
        peak = PeakSchedule.from_yaml(affinity.raw["routing"])
        return cls(affinity, budget_gate, alert_pipeline, peak, mongo_client, logger)

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
        """
        t0 = time.perf_counter()
        reason: list[str] = []

        # -------------------------------------------------------------------
        # Step 1: Context loaded by caller (already in ctx).
        # -------------------------------------------------------------------
        reason.append(f"task_type={ctx.task_type}")
        reason.append(f"agent={ctx.agent_id}")

        # -------------------------------------------------------------------
        # Step 2: Budget gate (HARD STOP)
        # -------------------------------------------------------------------
        if ctx.goal_id and ctx.goal_id.strip():
            allow, gate_reason = self.budget_gate.check(ctx.goal_id, ctx.priority)
        else:
            allow, gate_reason = True, "no_goal"

        reason.append(f"budget={gate_reason}")
        # force_local is True if P1 bypass with force_local semantics, OR if blocked
        force_local = ("force_local" in gate_reason) or (not allow)

        if not allow:
            # Hard stop: return local-only chain immediately (skip steps 3-7)
            local_models = self._select_local_only(ctx)
            decision = self._finalize(
                ctx,
                primary=local_models[0] if local_models else "ollama/llama3.2",
                fallback=local_models[1:] if len(local_models) > 1 else [],
                reason=reason,
                peak=False,
                mode=ctx.brain_context.get("mode", "exploration"),
                force_local=True,
                t0=t0,
            )
            self._log_decision(decision)
            return decision

        # -------------------------------------------------------------------
        # Step 3: Select candidates from affinity map
        # -------------------------------------------------------------------
        chain = self.affinity.lookup(ctx.agent_id, ctx.task_type)
        candidates: list[str] = []
        for tier in ("primary", "secondary", "local"):
            candidates.extend(chain[tier])
        reason.append(f"affinity={ctx.agent_id}.{ctx.task_type}")

        # -------------------------------------------------------------------
        # Step 4: Brain-mode filter (hard for stabilization, soft for others)
        # -------------------------------------------------------------------
        mode = ctx.brain_context.get("mode", "exploration")
        if mode == "stabilization":
            before = len(candidates)
            candidates = [m for m in candidates if self.affinity.is_stabilization_safe(m)]
            reason.append(f"stabilization_filter:{before}->{len(candidates)}")
            if not candidates:
                # Pathological: no safe model at all — fall through to local tier
                candidates = list(chain["local"])
                reason.append("stabilization_fallthrough_to_local")
        else:
            # exploration or exploitation — soft preference (retain full set, weights adjusted later)
            reason.append(f"mode={mode}_soft")

        # -------------------------------------------------------------------
        # Step 5: Latency filter (drop models exceeding ctx.latency_sla_ms)
        # -------------------------------------------------------------------
        before_lat = len(candidates)
        latency_filtered = [
            m for m in candidates
            if self._meta_for(m).get("latency_ms", 5000) <= ctx.latency_sla_ms
        ]
        if not latency_filtered:
            # SLA too strict — relax to local tier (always fastest)
            candidates = list(chain["local"]) or candidates
            reason.append("latency_relaxed_to_local")
        else:
            candidates = latency_filtered
            reason.append(f"latency_filter:{before_lat}->{len(candidates)}")

        # -------------------------------------------------------------------
        # Step 6: Peak/off-peak modifier
        # -------------------------------------------------------------------
        peak = self.peak_schedule.is_peak()
        # Start with mode weights from affinity config
        weights = dict(self.affinity.mode_weights.get(mode, {"quality": 0.6, "cost": 0.25, "latency": 0.15}))

        if peak:
            # HARD tier-shift: drop primary tier from "primary slot" (kept in fallback)
            non_primary = [c for c in candidates if self._meta_for(c).get("tier") != "primary"]
            if non_primary:
                candidates = non_primary
            reason.append("peak_hard_shift")
        else:
            # SOFT boost: quality weight × 1.25 (other weights re-normalized)
            boosted_q = min(weights["quality"] * 1.25, 0.99)
            remaining = 1.0 - boosted_q
            cost_w = weights.get("cost", 0.25)
            lat_w = weights.get("latency", 0.15)
            denom = cost_w + lat_w
            if denom > 0:
                weights["quality"] = boosted_q
                weights["cost"] = cost_w / denom * remaining
                weights["latency"] = lat_w / denom * remaining
            reason.append("offpeak_quality_boost")

        # If force_local from p1_bypass_force_local, restrict to local tier only
        if force_local:
            local_only = [c for c in candidates if self._meta_for(c).get("tier") == "local"]
            if not local_only:
                local_only = list(chain["local"])
            candidates = local_only
            reason.append("force_local")

        # -------------------------------------------------------------------
        # Step 7: Build fallback chain (score candidates, pick primary, ensure local)
        # -------------------------------------------------------------------
        # Score and rank candidates
        scored = sorted(
            ((self._composite(m, weights), m) for m in candidates),
            key=lambda x: x[0],
            reverse=True,
        )
        ordered = [m for _, m in scored]

        # primary = top score
        primary = ordered[0]
        fallback: list[str] = []
        primary_tier = self._meta_for(primary).get("tier")

        # Build fallback: prefer tier diversity
        seen_tiers = {primary_tier}
        for m in ordered[1:]:
            if m == primary:
                continue
            m_tier = self._meta_for(m).get("tier")
            if m_tier in seen_tiers and m_tier != "local":
                continue  # prefer tier diversity; local may repeat
            fallback.append(m)
            seen_tiers.add(m_tier)
            if len(fallback) >= 2:
                break

        # Guarantee: chain MUST contain a local tier model
        all_in_chain = [primary, *fallback]
        if not any(self._meta_for(x).get("tier") == "local" for x in all_in_chain):
            local_candidates = list(chain["local"])
            if local_candidates and local_candidates[0] not in all_in_chain:
                fallback.append(local_candidates[0])

        # Cap fallback at 2 (CONTEXT.md: 3-tier chain {primary, fallback:[secondary, local]})
        fallback = fallback[:2]

        # -------------------------------------------------------------------
        # Step 8: Log decision (MANDATORY)
        # -------------------------------------------------------------------
        decision = self._finalize(
            ctx,
            primary=primary,
            fallback=fallback,
            reason=reason,
            peak=peak,
            mode=mode,
            force_local=force_local,
            t0=t0,
        )
        self._log_decision(decision)
        return decision

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _meta_for(self, model_id: str) -> dict:
        """Safe metadata lookup — returns {} for unknown models."""
        try:
            return self.affinity.get_model_meta(model_id)
        except (KeyError, AttributeError):
            return {}

    def _composite(self, model_id: str, weights: dict) -> float:
        """Compute composite score for a model given weights."""
        q = _scoring.compute_quality_score(model_id, self.affinity.models)
        c = _scoring.compute_cost_score(model_id, self.affinity.models)
        la = _scoring.compute_latency_score(model_id, self.affinity.models)
        return _scoring.compute_composite(q, c, la, weights)

    def _select_local_only(self, ctx: RouterContext) -> list[str]:
        """Return local-tier models from affinity lookup (used for hard-stop path)."""
        chain = self.affinity.lookup(ctx.agent_id, ctx.task_type)
        return list(chain.get("local", []))

    def _finalize(
        self,
        ctx: RouterContext,
        primary: str,
        fallback: list[str],
        reason: list[str],
        peak: bool,
        mode: str,
        force_local: bool,
        t0: float,
    ) -> RoutingDecision:
        """Construct the RoutingDecision from pipeline results."""
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RoutingDecision(
            task_id=ctx.task_id,
            goal_id=ctx.goal_id or "",
            agent_id=ctx.agent_id,
            task_type=ctx.task_type,
            primary=primary,
            fallback=fallback,
            reason=reason,
            decision_time_ms=elapsed_ms,
            selected_model=primary,
            peak=peak,
            mode=mode,
            force_local=force_local,
        )

    def _log_decision(self, decision: RoutingDecision) -> None:
        """
        Step 8 (mandatory): emit structured JSON log to stdout + persist to MongoDB.

        8 required fields: task_id, goal_id, agent_id, task_type,
                           selected_model, fallback, reason, decision_time_ms.
        """
        payload = decision.model_dump(mode="json")
        self.log.info(json.dumps({"event": "router_decision", **payload}))
        if self.mongo is not None:
            try:
                import uuid as _uuid
                self.mongo.fingpt_agents.router_decisions.insert_one(
                    {
                        "_id": str(_uuid.uuid4()),
                        **decision.model_dump(mode="python"),
                        "created_at": datetime.now(timezone.utc),
                    }
                )
            except Exception as e:
                self.log.warning(
                    json.dumps(
                        {"event": "router_decision_mongo_error", "error": str(e)}
                    )
                )
