"""Phase 43.1 utility-path post-call hook.

Mirrors chat-side chat_model_call_after/_router_log_cost.py with two key differences:
  1. NO 'reasoning' arg — utility hooks fire without it.
     agent.py:788 fires: call_extensions_async("util_model_call_after", self, call_data=call_data, response=response)
     The reasoning string is discarded in call_utility_model (assigned to _reasoning and not passed on).
  2. Token estimate is tc.count(response) ONLY — no reasoning component.
     Utility calls are non-streaming by default; no reasoning callback passed.

CostRecord written with path='utility'. Redis aggregates and AlertPipeline are PATH-AGNOSTIC —
same shared Redis keys (router:budget:goal:*, router:budget:agent:*, router:budget:system) as chat.
force_local + P1 bypass apply symmetrically (handled inside BudgetGate.check() which router called
in the decide() phase; increment_spend always runs regardless).

Phase 43 conventions inherited:
  - _id = str(uuid.uuid4()) on all MongoDB inserts
  - schema_version = 1 on agent_runs inserts
  - Empty/unknown task_id gets 'ui-<hex12>' sentinel (set by _20_router_decide.py already)

Signature:
    execute(self, call_data: dict = None, response: str = "", **kwargs)
    Fired by: call_extensions_async("util_model_call_after", self, call_data=call_data, response=response)
"""
import os
import time
import uuid
from datetime import datetime, timezone
from helpers.extension import Extension
from emitters.source_health_registry import SourceHealthRegistry


def _estimate_tokens(text: str) -> int:
    """Estimate token count via tiktoken (gpt-4 encoding) with character fallback."""
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(text or ""))
    except Exception:
        # Fallback: ~4 chars/token (rough estimate, acceptable for cost tracking)
        return max(1, len(text or "") // 4)


class UtilModelRouterLogCost(Extension):
    """
    Phase 43.1 utility post-call hook: cost capture + budget increment + alert evaluation.

    Reads from agent.data:
        _util_router_pending_decision  — RoutingDecision (set by _20_router_decide.py)
        _util_router_call_start_ms     — call start timestamp in ms
        _util_router_context           — {task_id, goal_id, agent_id, task_type}
        model_router                   — ModelRouter (with budget_gate + alert_pipeline)
        mongo_client                   — MongoDB client for agent_runs write

    Writes:
        MongoDB fingpt_agents.agent_runs  — CostRecord with path='utility'
        Redis router:budget:*             — via BudgetGate.increment_spend (shared pool)
        AlertPipeline sinks               — evaluated for all 3 scopes
    """

    async def execute(self, call_data: dict = None, response: str = "", **kwargs):
        """
        Post-call cost capture.

        NOTE: This hook does NOT receive 'reasoning' (unlike chat-side _router_log_cost.py).
        Token estimation uses response only.
        """
        if not self.agent:
            return

        decision = self.agent.get_data("_util_router_pending_decision")
        if decision is None:
            # Router was not active for this call (no-op — decision was never stashed)
            return

        # Consume the pending decision (clear so a subsequent call doesn't reuse it)
        self.agent.set_data("_util_router_pending_decision", None)

        ctx_dict = self.agent.get_data("_util_router_context") or {}
        start_ms = self.agent.get_data("_util_router_call_start_ms") or (time.time() * 1000.0)
        latency_ms = max(0, int(time.time() * 1000.0 - start_ms))

        # ----------------------------------------------------------------
        # Token + cost estimation (utility: response only — no reasoning)
        # ----------------------------------------------------------------
        prompt_text = (call_data or {}).get("system", "") + "\n" + (call_data or {}).get("message", "")
        tokens_in = _estimate_tokens(prompt_text)
        tokens_out = _estimate_tokens(response or "")
        tokens_total = tokens_in + tokens_out

        # Cost from model catalog metadata via router._meta_for
        # Fallback: 0.0 if model metadata unavailable (cost tracking degrades gracefully)
        cost_usd = 0.0
        try:
            router = self.agent.get_data("model_router")
            if router and decision.primary:
                meta = router._meta_for(decision.primary) or {}
                cost_per_1k_out = float(meta.get("cost_per_1k_output_usd", 0.0))
                cost_per_1k_in = float(meta.get("cost_per_1k_input_usd", cost_per_1k_out / 4.0))
                cost_usd = (
                    (tokens_in / 1000.0) * cost_per_1k_in
                    + (tokens_out / 1000.0) * cost_per_1k_out
                )
        except Exception:
            cost_usd = 0.0  # Cost extraction is Phase 43.2 normalization layer; degrade gracefully

        # ----------------------------------------------------------------
        # Phase 43.2: Read failover result from agent.data cross-hook carrier.
        #
        # execute_with_fallback stashes {model, chain_index, fallback_used, attempt_count}
        # on success. If present, use the ACTUAL model called (not decision.primary).
        # If absent (failover wrapper not installed), default to decision.primary.
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
        # 1. CostRecord write to MongoDB agent_runs with path='utility'
        #    Phase 43 conventions: _id = str(uuid4()), schema_version = 1
        # ----------------------------------------------------------------
        try:
            mongo_client = self.agent.get_data("mongo_client")
            if mongo_client is None:
                # Lazy fallback for resumed-chat path (agent_init not re-fired)
                mongo_uri = os.environ.get("MONGODB_URI")
                if mongo_uri:
                    import pymongo
                    # serverSelectionTimeoutMS bounds the (lazy) first op so a
                    # down Mongo cannot stall a per-utility-model-call (A3;
                    # mirrors the timed chat sibling _router_decide.py:54).
                    mongo_client = pymongo.MongoClient(
                        mongo_uri,
                        serverSelectionTimeoutMS=int(os.getenv("A0_MONGO_TIMEOUT_MS", "5000")),
                    )

            if mongo_client is not None:
                # 2026-06-11 — additive conversation_type tag (chat-side hook
                # mirrors the same write). Drives the AI Routing telemetry
                # panel's 6 conv-type rows. Utility-path calls usually lack
                # an explicit conv_type; the tag is omitted in that case.
                conv_type = self.agent.get_data("conversation_type")
                record = {
                    "_id": str(uuid.uuid4()),
                    "schema_version": 1,
                    "task_id": ctx_dict.get("task_id"),
                    "goal_id": ctx_dict.get("goal_id", ""),
                    "agent_id": ctx_dict.get("agent_id", "agent_zero"),
                    "model": actual_model,      # Phase 43.2: ACTUAL model called (not decision.primary)
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "tokens": tokens_total,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "path": "utility",          # Phase 43.1: cost-separation field
                    "chain_index": chain_index,      # Phase 43.2: 0 = primary, N = Nth fallback
                    "fallback_used": fallback_used,  # Phase 43.2: True iff chain_index > 0
                    "attempt_count": attempt_count,  # Phase 43.2: total attempts made
                    "created_at": datetime.now(timezone.utc),
                }
                if conv_type:
                    record["conversation_type"] = conv_type
                # Use dot notation (same as chat-side hook and agent_init pattern)
                # insert_one is the first real Mongo op — bounded by
                # serverSelectionTimeoutMS above.
                mongo_client.fingpt_agents.agent_runs.insert_one(record)
                SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
        except Exception as e:
            # Emit the health signal alongside the existing swallow-and-log (D-07).
            SourceHealthRegistry.get_shared_instance().report(
                "mongo", available=False, failure_reason=str(e)
            )
            if hasattr(self.agent, "log") and hasattr(self.agent.log, "log"):
                self.agent.log.log(type="warning", heading=f"util_cost_record_failed: {e}")

        # ----------------------------------------------------------------
        # 2. Redis aggregate increment via BudgetGate.increment_spend
        #    PATH-AGNOSTIC: same shared Redis keys as chat path
        #    router:budget:goal:{goal_id}, router:budget:agent:{agent_type}, router:budget:system
        # ----------------------------------------------------------------
        router = self.agent.get_data("model_router")
        updated_goal = {}
        if router and router.budget_gate:
            try:
                goal_id = ctx_dict.get("goal_id", "")
                agent_id = ctx_dict.get("agent_id", "agent_zero")

                # auto_resume_check: midnight date rollover resets breach state
                # Run BEFORE increment so a midnight rollover zeroes aggregates first.
                if goal_id:
                    router.budget_gate.auto_resume_check(goal_id)

                # increment_spend updates goal + agent_type + system Redis keys in one call
                updated_goal = router.budget_gate.increment_spend(goal_id, agent_id, cost_usd) or {}
            except Exception as e:
                if hasattr(self.agent, "log") and hasattr(self.agent.log, "log"):
                    self.agent.log.log(type="warning", heading=f"util_redis_increment_failed: {e}")

        # ----------------------------------------------------------------
        # 3. AlertPipeline evaluate + fire for all 3 scopes (path-agnostic)
        #    Same evaluation pattern as chat-side _router_log_cost.py
        # ----------------------------------------------------------------
        if router and router.alert_pipeline and router.budget_gate:
            try:
                goal_id = ctx_dict.get("goal_id", "")
                agent_id = ctx_dict.get("agent_id", "agent_zero")

                # Scope 1: per-goal
                # max_usd from goal doc warmed into Redis by BudgetGate._warm_from_mongo
                if goal_id and updated_goal:
                    g_spent = float(updated_goal.get("spent_usd", 0.0))
                    g_max_raw = updated_goal.get("max_usd", "inf")
                    try:
                        g_max = float(g_max_raw) if g_max_raw not in ("inf", "Infinity", None) else float("inf")
                    except (ValueError, TypeError):
                        g_max = float("inf")
                    if g_max > 0 and g_max != float("inf"):
                        router.alert_pipeline.evaluate_and_fire("goal", goal_id, g_spent, g_max)

                # Scope 2: per-agent-type
                # max_usd from injected budget_caps; spent from Redis aggregate
                agent_agg = router.budget_gate.get_agent_type_aggregate(agent_id)
                a_spent = float(agent_agg.get("spent_usd", 0.0))
                a_max = float(agent_agg.get("max_usd", 0.0))
                if a_max > 0:
                    router.alert_pipeline.evaluate_and_fire("agent_type", agent_id, a_spent, a_max)

                # Scope 3: system-wide
                sys_agg = router.budget_gate.get_system_aggregate()
                s_spent = float(sys_agg.get("spent_usd", 0.0))
                s_max = float(sys_agg.get("max_usd", 0.0))
                if s_max > 0:
                    router.alert_pipeline.evaluate_and_fire("system", "system", s_spent, s_max)

            except Exception as e:
                if hasattr(self.agent, "log") and hasattr(self.agent.log, "log"):
                    self.agent.log.log(type="warning", heading=f"util_alert_pipeline_failed: {e}")
