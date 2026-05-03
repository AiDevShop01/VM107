"""Phase 43 post-call cost capture + multi-scope alert evaluation.

Extracts token/cost/latency after each LLM call, writes CostRecord to MongoDB
agent_runs, increments Redis aggregates (goal/agent_type/system) via
BudgetGate.increment_spend, runs auto_resume_check, then evaluates
AlertPipeline for ALL THREE scopes independently:
  - goal scope:       max_usd from updated goal aggregate (Redis HSET)
  - agent_type scope: max_usd from BudgetGate.get_agent_type_aggregate(agent_id)
                      (which reads Redis spent + budget_caps['agent_types'][agent_id])
  - system scope:     max_usd from BudgetGate.get_system_aggregate()
                      (which reads Redis spent + budget_caps['system'])

Scopes with max_usd<=0 are skipped (no cap configured in model_routing.yaml).

CONTEXT.md contract: "all three scopes evaluated independently after every
cost-incurring task" — this is the execution point.

Token/cost estimation follows _15_boundary_token_capture.py pattern:
  LiteLLM usage metadata is consumed inside unified_call() and not exposed
  to extension hooks. We estimate via TokenCounter + CostCalculator (tiktoken
  estimate). Cost will be approximate for API models; exact for local (cost=0).

Graceful no-op when:
  - self.agent is None
  - router_decision not in params_temporary (routing was skipped)
  - model_router not on agent.data (not initialized)
"""
import json
import logging
import time
from datetime import datetime, timezone
from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("router.chat_model_call_after")


class ModelRouterLogCost(Extension):
    """
    Post-call extension: capture cost + persist records + evaluate alerts.

    Reads: loop_data.params_temporary["router_decision"]
           agent.data["model_router"]     — ModelRouter (with budget_gate + alert_pipeline)
           agent.data["router_context"]   — goal_id, agent_id, task_id
           agent.data["mongo_client"]     — MongoDB client for agent_runs write
    Writes: MongoDB agent_runs (CostRecord)
            Redis router:budget:* (via BudgetGate.increment_spend)
    """

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        call_data: dict = None,
        response: str = "",
        reasoning: str = "",
        **kwargs,
    ):
        if not self.agent:
            return

        decision = (
            loop_data.params_temporary.get("router_decision") if loop_data else None
        )
        # Fallback: chat_model_call_after doesn't receive loop_data from agent.py:832,
        # so the loop_data above is the empty default LoopData(). Read from agent.data.
        if decision is None:
            decision = self.agent.get_data("_router_pending_decision")
        if decision is None:
            return  # router was not active for this call
        # Clear the pending decision so a subsequent call doesn't reuse this one
        # if for any reason _router_decide.py doesn't stash a new decision.
        self.agent.set_data("_router_pending_decision", None)

        router = self.agent.get_data("model_router")
        if router is None:
            return

        ctx_data = self.agent.get_data("router_context") or {}
        goal_id = ctx_data.get("goal_id") or ""
        agent_id = ctx_data.get("agent_id") or getattr(self.agent, "agent_name", "agent_zero")
        task_id = ctx_data.get("task_id") or decision.task_id

        # ----------------------------------------------------------------
        # Token + cost estimation (tiktoken estimate, follows Phase 38 pattern)
        # ----------------------------------------------------------------
        call_start = (loop_data.params_temporary.get("_router_call_start_ms", 0) if loop_data else 0) \
            or self.agent.get_data("_router_call_start_ms") \
            or 0
        latency_ms = int((time.time() * 1000) - call_start) if call_start else 0

        try:
            from core.boundary.token_counter import TokenCounter
            from core.boundary.cost_calculator import CostCalculator
            tc = TokenCounter()
            cc = CostCalculator()
            tokens = tc.count(response or "") + tc.count(reasoning or "")
            cost_usd = cc.calculate(decision.primary, tokens, tokens)
        except Exception as e:
            log.warning(json.dumps({"event": "cost_estimate_failed", "error": str(e)}))
            tokens, cost_usd = 0, 0.0

        # ----------------------------------------------------------------
        # Phase 43.2: Read failover result from agent.data cross-hook carrier.
        #
        # execute_with_fallback stashes {model, chain_index, fallback_used, attempt_count}
        # on success. If present, use the ACTUAL model called (not decision.primary).
        # If absent (failover wrapper not installed or primary succeeded in legacy mode),
        # default to decision.primary with chain_index=0, fallback_used=False.
        # Clear the stash after reading to prevent bleed between calls.
        # ----------------------------------------------------------------
        failover_result = self.agent.get_data("_router_failover_result")
        if failover_result:
            actual_model = failover_result.get("model", decision.primary)
            chain_index = failover_result.get("chain_index", 0)
            fallback_used = failover_result.get("fallback_used", False)
            attempt_count = failover_result.get("attempt_count", 1)
            # Clear carrier so subsequent calls don't reuse stale result
            self.agent.set_data("_router_failover_result", None)
        else:
            # Legacy path (failover wrapper not installed) or primary succeeded with no stash
            actual_model = decision.primary
            chain_index = 0
            fallback_used = False
            attempt_count = 1

        # ----------------------------------------------------------------
        # Build CostRecord
        # ----------------------------------------------------------------
        from core.routing.schemas import CostRecord
        record = CostRecord(
            task_id=task_id,
            model=actual_model,           # Phase 43.2: ACTUAL model called (not decision.primary)
            tokens=tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            goal_id=goal_id,
            agent_id=agent_id,
            chain_index=chain_index,      # Phase 43.2: 0 = primary, N = Nth fallback
            fallback_used=fallback_used,  # Phase 43.2: True iff chain_index > 0
            attempt_count=attempt_count,  # Phase 43.2: total attempts made
        )
        log.info(json.dumps({"event": "router_cost_record", **record.model_dump(mode="json")}))

        # ----------------------------------------------------------------
        # Persist to MongoDB agent_runs
        # ----------------------------------------------------------------
        try:
            mongo = self.agent.get_data("mongo_client")
            if mongo is not None:
                import uuid as _uuid
                mongo.fingpt_agents.agent_runs.insert_one(
                    {
                        "_id": str(_uuid.uuid4()),
                        "schema_version": 1,
                        **record.model_dump(mode="python"),
                        "created_at": datetime.now(timezone.utc),
                    }
                )
        except Exception as e:
            log.warning(json.dumps({"event": "cost_record_mongo_error", "error": str(e)}))

        # ----------------------------------------------------------------
        # Increment Redis aggregates + evaluate alerts for ALL THREE scopes.
        # CONTEXT.md: "all three scopes evaluated independently after every
        # cost-incurring task".
        # ----------------------------------------------------------------
        try:
            # auto_resume_check: midnight date rollover resets all breach state
            # Run BEFORE increment so a midnight rollover zeroes aggregates first.
            if goal_id:
                router.budget_gate.auto_resume_check(goal_id)

            # increment_spend touches goal + agent_type + system Redis keys in one call;
            # returns the updated goal aggregate HGETALL for immediate threshold evaluation.
            # Always call it — agent_type + system aggregates apply even for goal-less UI
            # calls; budget_gate.increment_spend handles empty goal_id gracefully.
            updated_goal = router.budget_gate.increment_spend(goal_id, agent_id, cost_usd)

            # ----- Scope 1: per-goal -----
            # max_usd comes from the goal document (warmed into Redis by BudgetGate._warm_from_mongo).
            # If max_usd is missing or infinite, no cap configured → skip alert eval.
            if goal_id and updated_goal:
                g_spent = float(updated_goal.get("spent_usd", 0.0))
                g_max_raw = updated_goal.get("max_usd", "inf")
                try:
                    g_max = float(g_max_raw) if g_max_raw not in ("inf", "Infinity", None) else float("inf")
                except (ValueError, TypeError):
                    g_max = float("inf")
                if g_max > 0 and g_max != float("inf"):
                    router.alert_pipeline.evaluate_and_fire("goal", goal_id, g_spent, g_max)

            # ----- Scope 2: per-agent-type -----
            # max_usd comes from injected budget_caps; spent from Redis aggregate.
            # max_usd=0.0 sentinel means no cap configured → skip.
            agent_aggregate = router.budget_gate.get_agent_type_aggregate(agent_id)
            a_spent = float(agent_aggregate.get("spent_usd", 0.0))
            a_max = float(agent_aggregate.get("max_usd", 0.0))
            if a_max > 0:
                router.alert_pipeline.evaluate_and_fire("agent_type", agent_id, a_spent, a_max)

            # ----- Scope 3: system-wide -----
            system_aggregate = router.budget_gate.get_system_aggregate()
            s_spent = float(system_aggregate.get("spent_usd", 0.0))
            s_max = float(system_aggregate.get("max_usd", 0.0))
            if s_max > 0:
                router.alert_pipeline.evaluate_and_fire("system", "system", s_spent, s_max)

        except Exception as e:
            log.warning(
                json.dumps({"event": "post_call_aggregate_error", "error": str(e)})
            )
