"""Phase 43 router selection — Step 1 of two-extension swap pattern.

Fires before main LLM call; runs the 8-step routing pipeline; stashes the
RoutingDecision in loop_data.params_temporary for the chat_model_call_before
extension to consume.

Hook invocation order (from agent.py):
  1. before_main_llm_call fires   ← THIS file stashes decision
  2. call_chat_model() invoked
  3. chat_model_call_before fires ← _router_apply.py reads & applies decision
  4. LiteLLM call executes
  5. chat_model_call_after fires  ← _router_log_cost.py logs cost

Graceful no-op when:
  - self.agent is None (called outside agent context)
  - redis_client / mongo_client / signal_accumulator not on agent.data
  - any unexpected exception during routing (logs error, never crashes agent)
"""
import os
import json
import logging
from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("router.before_main_llm_call")

ROUTING_YAML = os.environ.get("ROUTER_CONFIG_PATH", "/a0/conf/model_routing.yaml")


def _get_or_init_router(agent):
    """Lazy-init ModelRouter cached on agent.data — follows _15_boundary_token_capture pattern."""
    router = agent.get_data("model_router")
    if router is not None:
        return router
    try:
        from core.routing.router import ModelRouter
        redis_client = agent.get_data("redis_client")
        mongo_client = agent.get_data("mongo_client")
        signal_accumulator = agent.get_data("signal_accumulator")

        # Fallback: construct deps from env if agent_init didn't wire them.
        # Triggers for resumed chats where Agent was restored from cache (persist_chat.py:245)
        # rather than freshly constructed via Agent.__init__ → agent_init.
        if not redis_client:
            try:
                import redis
                redis_client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
                agent.set_data("redis_client", redis_client)
            except Exception as e:
                log.error(json.dumps({"event": "router_lazy_redis_failed", "error": str(e)}))
        if not mongo_client:
            try:
                from pymongo import MongoClient
                mongo_client = MongoClient(os.environ["MONGODB_URI"], retryWrites=True, w="majority", serverSelectionTimeoutMS=5000)
                agent.set_data("mongo_client", mongo_client)
            except Exception as e:
                log.error(json.dumps({"event": "router_lazy_mongo_failed", "error": str(e)}))
        if not signal_accumulator:
            try:
                from core.scheduling.signals import SignalAccumulator
                signal_accumulator = SignalAccumulator()
                agent.set_data("signal_accumulator", signal_accumulator)
            except Exception as e:
                log.error(json.dumps({"event": "router_lazy_signal_failed", "error": str(e)}))

        if not (redis_client and mongo_client and signal_accumulator):
            log.warning(
                json.dumps(
                    {
                        "event": "router_init_skipped",
                        "reason": "missing_deps",
                        "redis": bool(redis_client),
                        "mongo": bool(mongo_client),
                        "signal_accumulator": bool(signal_accumulator),
                    }
                )
            )
            return None
        router = ModelRouter.from_yaml(
            ROUTING_YAML,
            redis_client=redis_client,
            mongo_client=mongo_client,
            signal_accumulator=signal_accumulator,
            logger=log,
        )
        agent.set_data("model_router", router)
        return router
    except Exception as e:
        log.error(json.dumps({"event": "router_init_failed", "error": str(e)}))
        return None


def _build_router_context(agent):
    """Extract RouterContext from agent.data (set by AgentRunner.start(task=) in Plan 01)."""
    from core.routing.schemas import RouterContext
    ctx_data = agent.get_data("router_context") or {}
    runner = agent.get_data("runner")
    # Prefer task_id from router_context; fall back to Phase 36 ExecutionContext
    if runner and hasattr(runner, "execution_context") and runner.execution_context:
        ec_task_id = getattr(runner.execution_context, "task_id", "unknown")
    else:
        ec_task_id = "unknown"

    task_id = ctx_data.get("task_id", ec_task_id)
    # UI-driven calls have no scheduler task_id; generate a unique one per call so
    # the unique index on router_decisions.task_id doesn't reject repeat conversations.
    if task_id == "unknown":
        import uuid as _uuid
        task_id = f"ui-{_uuid.uuid4().hex[:12]}"
    # Brain context: set by Phase 42 brain integration on agent.data; empty dict = exploration default
    brain_ctx = agent.get_data("brain_context") or {}

    return RouterContext(
        task_id=task_id,
        goal_id=ctx_data.get("goal_id", ""),
        agent_id=ctx_data.get("agent_id", getattr(agent, "agent_name", "agent_zero")),
        task_type=ctx_data.get("task_type", "default"),
        priority=ctx_data.get("priority", "P3"),
        latency_sla_ms=ctx_data.get("latency_sla_ms", 30000),
        brain_context=brain_ctx,
    )


class ModelRouterSelect(Extension):
    """
    Pre-call extension: runs the 8-step routing pipeline and stashes the decision.

    Stored at: loop_data.params_temporary["router_decision"]
    Consumed by: chat_model_call_before/_router_apply.py
    """

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        router = _get_or_init_router(self.agent)
        if router is None:
            return  # graceful no-op: agent will use default model

        try:
            ctx = _build_router_context(self.agent)
            decision = router.decide(ctx)
            loop_data.params_temporary["router_decision"] = decision
        except Exception as e:
            log.error(
                json.dumps({"event": "router_decide_failed", "error": str(e)})
            )
            # Graceful degradation: no decision stashed → apply extension is a no-op
