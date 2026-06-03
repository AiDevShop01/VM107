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

Phase 43.1 extension:
  - decide() now branches on ctx.path ("chat" or "utility")
  - Chat path refactored into _decide_chat() — behavior IDENTICAL to Phase 43
  - Utility path in _decide_utility() — cost-first weights, hard drop, aggressive latency

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

    Phase 43.1: decide() branches on ctx.path:
    - "chat"    → _decide_chat()    (Phase 43 behavior, unchanged)
    - "utility" → _decide_utility() (cost-first weights, hard drop expensive, no off-peak boost)

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

        Phase 43.1: branches on ctx.path after the shared Steps 1-2 (budget gate).
        Chat path unchanged (refactored into _decide_chat). Utility path new.

        Args:
            ctx: Immutable routing context (task_id, goal_id, agent_id, task_type,
                 priority, latency_sla_ms, brain_context, path)

        Returns:
            RoutingDecision with primary + fallback chain and structured reason list.
            path field on RoutingDecision mirrors ctx.path.
        """
        t0 = time.perf_counter()
        reason: list[str] = []

        # -------------------------------------------------------------------
        # Step 1: Context loaded by caller (already in ctx).
        # Phase 43.1: path tag prepended so every reason chain is self-describing.
        # -------------------------------------------------------------------
        reason.append(f"path={ctx.path}")
        reason.append(f"task_type={ctx.task_type}")
        reason.append(f"agent={ctx.agent_id}")

        # -------------------------------------------------------------------
        # Step 2: Budget gate (HARD STOP) — identical for both paths
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
        # Steps 3-7: BRANCH on path (Phase 43.1)
        # -------------------------------------------------------------------
        if ctx.path == "utility":
            return self._decide_utility(ctx, reason, force_local, t0)
        return self._decide_chat(ctx, reason, force_local, t0)

    # -----------------------------------------------------------------------
    # Path: Chat (Phase 43 behavior — exactly preserved, extracted from decide())
    # -----------------------------------------------------------------------

    def _decide_chat(
        self, ctx: RouterContext, reason: list[str], force_local: bool, t0: float
    ) -> RoutingDecision:
        """
        Steps 3-7 for the chat path.

        Extracted from Phase 43's decide() with ZERO behavior changes.
        Mode weights from YAML, optional off-peak quality boost, stabilization hard filter.
        """
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
        # Step 6: Peak/off-peak modifier (chat path: off-peak quality boost allowed)
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
    # Path: Utility (Phase 43.1 — cost-first weights, hard drop, no off-peak boost)
    # -----------------------------------------------------------------------

    def _decide_utility(
        self, ctx: RouterContext, reason: list[str], force_local: bool, t0: float
    ) -> RoutingDecision:
        """
        Steps 3-7 for the utility path.

        Key differences from _decide_chat:
        1. Candidates from utility: YAML block (NEVER chat affinity — defeats cost separation)
        2. allow_chat_models=true override: use chat affinity chain but WITH utility weights
        3. HARD DROP models above cost_thresholds.expensive_usd_per_1k_output (utility-only)
        4. Brain mode SOFT ONLY — no hard stabilization filter (utility is always cheap)
        5. Latency filter uses ctx.latency_sla_ms (utility SLA, e.g. 2000ms for execution)
        6. Peak: tier-shift still applies; off-peak does NOT boost quality_weight (LOCKED)
        7. Scoring always uses FIXED {quality: 0.2, cost: 0.5, latency: 0.3} weights
        """
        # -------------------------------------------------------------------
        # Step 3: Get utility candidates (from utility: YAML block)
        # NEVER falls through to affinity[chat] — anti-pattern per CONTEXT.md
        # -------------------------------------------------------------------
        chain = self.affinity.utility_lookup(ctx.task_type)
        reason.append(f"utility_{ctx.task_type}")

        # Override escape hatch: allow_chat_models=true uses chat affinity chain
        # with utility cost-first weights (preserves cost discipline)
        if chain.get("allow_chat_models"):
            chain = self.affinity.lookup(ctx.agent_id, ctx.task_type)
            reason.append("allow_chat_models_override")

        candidates: list[str] = []
        for tier in ("primary", "secondary", "local"):
            tier_models = chain.get(tier) or []
            candidates.extend(tier_models)

        # -------------------------------------------------------------------
        # Step 3b: HARD DROP expensive models (utility-only filter, not in chat path)
        # -------------------------------------------------------------------
        expensive_threshold = self.affinity.cost_thresholds.get("expensive_usd_per_1k_output", 0.02)
        before_drop = len(candidates)
        affordable = [
            m for m in candidates
            if self._meta_for(m).get("cost_per_1k_output_usd", 0.0) <= expensive_threshold
        ]
        if not affordable:
            # Pathological: all models expensive — force local
            candidates = list(chain.get("local") or []) or candidates
            reason.append("cost_filter_forced_local")
        else:
            candidates = affordable
            reason.append(f"cost_filter:{before_drop}->{len(candidates)}")

        # -------------------------------------------------------------------
        # Step 4: Brain mode — SOFT ONLY for utility path
        # Hard filter in stabilization would break execution capability.
        # Utility is already cheap by design, so mode rarely changes selection.
        # -------------------------------------------------------------------
        mode = ctx.brain_context.get("mode", "exploration")
        reason.append(f"mode={mode}_util_soft")

        # -------------------------------------------------------------------
        # Step 5: Aggressive latency filter using ctx.latency_sla_ms
        # ctx.latency_sla_ms was set by utility hook from get_utility_latency_sla()
        # e.g. 2000ms for execution, 3000ms for default
        # -------------------------------------------------------------------
        before_lat = len(candidates)
        lat_filtered = [
            m for m in candidates
            if self._meta_for(m).get("latency_ms", 5000) <= ctx.latency_sla_ms
        ]
        # If all filtered out, relax to local tier (fastest option)
        candidates = lat_filtered or list(chain.get("local") or []) or candidates
        reason.append(f"latency_filter:{before_lat}->{len(candidates)}")

        # -------------------------------------------------------------------
        # Step 6: Peak modifier — tier-shift on peak; off-peak NO quality boost (LOCKED)
        # Utility stays cost-first regardless of time of day (CONTEXT.md)
        # -------------------------------------------------------------------
        peak = self.peak_schedule.is_peak()
        # FIXED cost-first weights — never use mode_weights on utility path
        weights = {"quality": 0.2, "cost": 0.5, "latency": 0.3}

        if peak:
            # HARD tier-shift: prefer non-primary (even cheaper) during peak
            non_primary = [c for c in candidates if self._meta_for(c).get("tier") != "primary"]
            if non_primary:
                candidates = non_primary
            reason.append("peak_hard_shift")
        else:
            # LOCKED: off-peak does NOT boost quality_weight on utility path
            # Utility stays cost-first regardless of clock
            reason.append("offpeak_no_boost_utility")

        # If force_local from p1_bypass_force_local, restrict to local tier only
        if force_local:
            local_only = [c for c in candidates if self._meta_for(c).get("tier") == "local"]
            if not local_only:
                local_only = list(chain.get("local") or [])
            candidates = local_only or candidates
            reason.append("force_local")

        # -------------------------------------------------------------------
        # Step 7: Build fallback chain with cost-first weights
        # -------------------------------------------------------------------
        if not candidates:
            # Safety: nothing survived filters — use any local model
            candidates = list(chain.get("local") or ["ollama/llama3.2"])

        scored = sorted(
            ((self._composite(m, weights), m) for m in candidates),
            key=lambda x: x[0],
            reverse=True,
        )
        ordered = [m for _, m in scored]

        primary = ordered[0]
        fallback: list[str] = ordered[1:3]  # up to 2 fallbacks

        # -------------------------------------------------------------------
        # Step 8: Log decision (MANDATORY — same MongoDB write as chat path)
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
        # Use utility lookup for utility path, chat lookup for chat path
        if ctx.path == "utility":
            try:
                chain = self.affinity.utility_lookup(ctx.task_type)
            except KeyError:
                chain = {"local": ["ollama/llama3.2"]}
        else:
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
            path=ctx.path,  # Phase 43.1: path mirrors ctx.path on every RoutingDecision
        )

    def tier_down_for_overage(self, conv_types: frozenset) -> None:
        """Tier-down non-trade-path conv-types to cheaper fallback model.

        Called by ``BudgetThresholdMonitor`` when daily AI spend crosses 120%
        of ``DAILY_AI_BUDGET_USD``.  Mutates ``_conv_type_overrides`` so that
        subsequent routing decisions for the affected conv-types use a cheaper
        fallback model.

        Trade-path conv-types are **PROTECTED**.  Passing ``pre-trade``,
        ``execution``, or ``macro`` in ``conv_types`` raises immediately.
        Budget overage MUST NOT degrade execution quality (CONTEXT §22 lock +
        REQ-74-7).

        Parameters
        ----------
        conv_types:
            The set of conversation type identifiers to tier-down.  Must not
            include any trade-path types (``pre-trade``, ``execution``,
            ``macro``).

        Raises
        ------
        ValueError
            If ``conv_types`` intersects with the protected trade-path set.
        """
        _TRADE_PATH_CONV_TYPES_LOCKED: frozenset = frozenset(
            {"pre-trade", "execution", "macro"}
        )
        forbidden = frozenset(conv_types) & _TRADE_PATH_CONV_TYPES_LOCKED
        if forbidden:
            raise ValueError(
                f"Trade-path conv-types are protected from tier-down: "
                f"{sorted(forbidden)} (CONTEXT §22 lock). "
                f"Budget overage MUST NOT degrade execution quality."
            )

        # Initialize override map if it doesn't exist yet
        if not hasattr(self, "_conv_type_overrides"):
            self._conv_type_overrides = {}

        for ct in conv_types:
            fallback = self._fallback_model_for(ct)
            self._conv_type_overrides[ct] = fallback
            self.log.info(
                json.dumps({
                    "event": "tier_down_for_overage",
                    "conv_type": ct,
                    "fallback_model": fallback,
                    "reason": "daily_budget_120pct_overage",
                })
            )

    def _fallback_model_for(self, conv_type: str) -> str:
        """Return the configured fallback model for a given conversation type.

        Falls back to ``ollama/llama3.2`` if no per-type configuration exists.
        Override point for tests and future YAML-driven configuration.
        """
        # Future: look up per-conv-type fallback from affinity YAML.
        # v1: uniform local fallback (cheapest available).
        fallback_map = getattr(self.affinity, "cost_overage_fallback_map", {})
        return fallback_map.get(conv_type, "ollama/llama3.2")

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
