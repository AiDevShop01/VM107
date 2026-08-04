"""Phase 43.1 utility-path pre-call hook.

Single hook responsible for BOTH router.decide() AND model swap application.
Utility side has only 2 hook points (before/after), so collapsing decide+apply
avoids modifying Agent Zero core (Phase 36 boundary).

Mirrors the lazy-init env-fallback pattern from chat-side _router_decide.py to
survive resumed-chat scenarios where agent_init never re-fires.

Key implementation notes (from LiteLLMChatWrapper inspection in Plan 01 Task 1):
    - model_name is a Pydantic field (str), not a property
    - model_config: frozen=False, validate_assignment=False
    - Direct mutation IS SAFE: call_data["model"].model_name = decision.primary
    - Constructor signature: LiteLLMChatWrapper(model: str, provider: str, model_config=None, **kwargs)

Signature:
    execute(self, call_data: dict = None, **kwargs)
    call_data shape: {"model": LiteLLMChatWrapper, "system": str, "message": str,
                      "callback": Callable|None, "background": bool}
    Fired by: call_extensions_async("util_model_call_before", self, call_data=call_data)
"""
import os
import time
import uuid
from helpers.extension import Extension
from core.routing.schemas import RouterContext
from emitters.source_health_registry import SourceHealthRegistry


def _get_or_init_router(agent):
    """
    Lazy router construction — same pattern as chat-side _router_decide.py.

    First tries agent.get_data("model_router") (set by agent_init extension).
    On miss, constructs from MONGODB_URI / REDIS_URL env vars (resumed-chat fallback).
    Returns None if any required dependency is missing (graceful no-op).
    """
    router = agent.get_data("model_router") if agent else None
    if router is not None:
        return router

    # Env-based init (resumed-chat fallback — agent_init not re-fired on resume)
    try:
        from core.routing.affinity import AffinityMap
        from core.routing.budget_gate import BudgetGate
        from core.routing.alert_pipeline import AlertPipeline
        from core.routing.peak_schedule import PeakSchedule
        from core.routing.router import ModelRouter
        import pymongo
        import redis

        mongo_uri = os.environ.get("MONGODB_URI")
        redis_url = os.environ.get("REDIS_URL")
        if not (mongo_uri and redis_url):
            return None

        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "conf", "model_routing.yaml",
        )
        # serverSelectionTimeoutMS bounds the (lazy) first op so a down Mongo
        # cannot stall a per-utility-model-call (A3; mirrors the already-timed
        # chat sibling extensions/python/before_main_llm_call/_router_decide.py:54).
        mongo_client = pymongo.MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=int(os.getenv("A0_MONGO_TIMEOUT_MS", "5000")),
        )
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        affinity = AffinityMap.from_yaml(yaml_path)

        alert_pipeline = AlertPipeline(
            mongo_client=mongo_client,
            signal_accumulator=agent.get_data("signal_accumulator"),
            external_notifier=None,
        )
        budget_gate = BudgetGate(
            redis_client=redis_client,
            mongo_client=mongo_client,
            budget_caps=affinity.budget_caps,
        )
        budget_gate.alert_pipeline = alert_pipeline  # circular ref resolved post-construction

        peak_schedule = PeakSchedule.from_yaml(affinity.raw["routing"])
        router = ModelRouter(
            affinity=affinity,
            budget_gate=budget_gate,
            alert_pipeline=alert_pipeline,
            peak_schedule=peak_schedule,
            mongo_client=mongo_client,
        )
        agent.set_data("model_router", router)
        SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
        return router
    except Exception as e:
        # Degrade silently — no-op if any dep missing (Redis/Mongo unavailable in dev, etc.)
        # Emit the health signal alongside the existing swallow-and-log (D-07).
        SourceHealthRegistry.get_shared_instance().report(
            "mongo", available=False, failure_reason=str(e)
        )
        if hasattr(agent, "log") and hasattr(agent.log, "log"):
            agent.log.log(type="warning", heading=f"util_router_init_skipped: {e}")
        return None


def _resolve_task_id(agent, ctx_data: dict) -> str:
    """
    Match Phase 43 task_id discipline: real task_id > 'ui-<hex12>' sentinel.

    AgentRunner injects real task_id when running scheduled tasks.
    UI calls (no scheduler context) get 'ui-<hex12>' as a unique per-call ID.
    Empty string and "unknown" are treated as "no task" (same as UI call).
    """
    tid = (ctx_data or {}).get("task_id") or ""
    if tid and tid not in ("", "unknown"):
        return tid
    return f"ui-{uuid.uuid4().hex[:12]}"


class UtilModelRouterDecide(Extension):
    """
    Phase 43.1 utility pre-call hook: router.decide() + model swap in one step.

    Why one hook (not two like chat path)?
    util_model_call_before already has the mutable call_data dict with the model instance.
    The decide() result can be applied immediately here — no separate apply hook needed.
    This avoids touching Agent Zero core (Phase 36 boundary).

    Execution order relative to other util_model_call_before extensions:
    _10_mask_secrets.py runs first (numeric prefix), then _20_router_decide.py (this file).
    The mask_secrets extension runs BEFORE us, so call_data may have secrets redacted —
    but the model reference itself is unaffected.
    """

    async def execute(self, call_data: dict = None, **kwargs):
        if not self.agent or not call_data:
            return

        router = _get_or_init_router(self.agent)
        if router is None:
            # No router available (likely dev/test environment without Redis/Mongo)
            return

        ctx_data = self.agent.get_data("router_context") or {}
        task_type = ctx_data.get("task_type") or "default"

        ctx = RouterContext(
            task_id=_resolve_task_id(self.agent, ctx_data),
            goal_id=ctx_data.get("goal_id") or "",
            agent_id=ctx_data.get("agent_id") or getattr(self.agent, "agent_name", "agent_zero"),
            task_type=task_type,
            priority=ctx_data.get("priority") or "P3",
            latency_sla_ms=router.affinity.get_utility_latency_sla(task_type),
            brain_context=self.agent.get_data("brain_context") or {},
            path="utility",  # KEY DIFFERENCE FROM CHAT PATH
        )

        decision = router.decide(ctx)

        # APPLY: mutate call_data['model'].model_name directly.
        # Confirmed safe per Plan 01 LiteLLMChatWrapper inspection:
        #   model_name is a Pydantic field (str), frozen=False, validate_assignment=False.
        #   Direct mutation: call_data["model"].model_name = decision.primary
        if decision.primary and not decision.force_local:
            try:
                call_data["model"].model_name = decision.primary
            except (AttributeError, TypeError) as e:
                # Fallback for edge case: model_name has a setter that rejects the value,
                # or call_data["model"] is not a LiteLLMChatWrapper (unexpected type).
                # Log warning and skip — agent uses its default model for this call.
                if hasattr(self.agent, "log") and hasattr(self.agent.log, "log"):
                    self.agent.log.log(
                        type="warning",
                        heading=f"util_router_apply_failed: could not set model_name={decision.primary!r}: {e}"
                    )

            # ----------------------------------------------------------------
            # Phase 43.2: Install execute_with_fallback monkey-patch (utility path).
            #
            # Same pattern as chat-side _router_apply.py. Replaces
            # call_data["model"].unified_call with a wrapper that iterates
            # [primary] + fallback chain on retryable errors.
            #
            # Wire-site: agent.py calls call_data["model"].unified_call(...)
            # for utility calls too — same wire-site, same monkey-patch approach.
            #
            # CRITICAL: wrapper forces a0_retry_attempts=0 to disable Agent Zero's
            # internal retry loop (models.py:508). Pitfall 1 prevention.
            # ----------------------------------------------------------------
            try:
                from models import LiteLLMChatWrapper
                import json as _json
                import logging as _logging
                _log = _logging.getLogger("router.util_model_call_before")

                if isinstance(call_data["model"], LiteLLMChatWrapper):
                    from core.routing.failover_executor import execute_with_fallback
                    chain = [decision.primary] + (decision.fallback or [])
                    original_unified_call = call_data["model"].unified_call
                    wrapper_instance = call_data["model"]
                    agent_ref = self.agent
                    decision_ref = decision

                    async def _util_failover_unified_call(**kw):
                        # Force a0_retry_attempts=0 — disables Agent Zero internal retry (Pitfall 1)
                        kw["a0_retry_attempts"] = 0
                        return await execute_with_fallback(
                            call_fn=original_unified_call,
                            chain=chain,
                            decision=decision_ref,
                            set_model_name=lambda m: setattr(wrapper_instance, "model_name", m),
                            agent_data=agent_ref.data if agent_ref else None,
                            decision_id=getattr(decision_ref, "task_id", ""),
                            **kw,
                        )

                    call_data["model"].unified_call = _util_failover_unified_call
                    _log.debug(_json.dumps({
                        "event": "router_failover_patch_installed",
                        "path": "utility",
                        "chain": chain,
                        "task_id": decision.task_id,
                    }))
                else:
                    # Type guard: unexpected model type — skip failover, log warning
                    import json as _json2
                    import logging as _logging2
                    _log2 = _logging2.getLogger("router.util_model_call_before")
                    _log2.warning(_json2.dumps({
                        "event": "router_failover_skipped",
                        "path": "utility",
                        "reason": "call_data['model'] is not LiteLLMChatWrapper",
                        "actual_type": type(call_data["model"]).__name__,
                    }))
            except Exception as patch_err:
                # Failover patch failure is non-fatal: agent continues without failover
                if hasattr(self.agent, "log") and hasattr(self.agent.log, "log"):
                    self.agent.log.log(
                        type="warning",
                        heading=f"util_router_failover_patch_error: {patch_err}"
                    )

        # Stash decision + start time for util_model_call_after
        # (util hooks don't receive loop_data, so agent.data is the carrier)
        self.agent.set_data("_util_router_pending_decision", decision)
        self.agent.set_data("_util_router_call_start_ms", time.time() * 1000.0)
        # Stash the context dict for util_model_call_after (goal_id, agent_id, task_id)
        self.agent.set_data("_util_router_context", {
            "task_id": ctx.task_id,
            "goal_id": ctx.goal_id,
            "agent_id": ctx.agent_id,
            "task_type": ctx.task_type,
        })
