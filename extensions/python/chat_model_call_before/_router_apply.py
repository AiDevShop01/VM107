"""Phase 43 router apply — Step 2 of two-extension swap pattern.

Reads stashed RoutingDecision from loop_data.params_temporary, mutates
call_data["model"] to the chosen LiteLLMChatWrapper instance, and attaches
the fallback chain to call_data for reference by other extensions.

Phase 43.2 extension: monkey-patches call_data["model"].unified_call with
execute_with_fallback wrapper so the fallback chain is ACTUALLY executed on
retryable errors (previously it was decoration only).

Wire-site (confirmed Plan 01 agent.py:821 inspection):
  call_data["model"].unified_call(...) is the call site in agent.py.
  Replacing this method on the instance is safe — LiteLLMChatWrapper has
  model_config = ConfigDict(extra="allow", validate_assignment=False).

RESEARCH.md Open Question 2 — RESOLVED:
  LiteLLMChatWrapper.unified_call() does NOT accept a fallbacks= kwarg. It
  constructs its own acompletion() call with a custom retry loop (see models.py
  lines 473-600). The LiteLLM completion() fallbacks= kwarg is NOT threaded
  through unified_call(). Therefore:
  - We mutate call_data["model"] to the primary LiteLLMChatWrapper.
  - We attach call_data["router_fallback_chain"] with the ordered model IDs.
  - Phase 43.2 wires execute_with_fallback monkey-patch for actual failover.
  - This is documented in 43-05-SUMMARY.md under LiteLLM Fallback API Finding.

Graceful no-op when:
  - call_data is None
  - self.agent is None
  - router_decision not in params_temporary (router skipped / init failed)
  - get_chat_model() raises (unknown provider/model: log, skip swap)
  - call_data["model"] is not LiteLLMChatWrapper (failover skipped with warning)
"""
import json
import logging
from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("router.chat_model_call_before")


def _split_model_id(model_id: str) -> tuple[str, str]:
    """
    Split 'provider/model_name' into ('provider', 'model_name').

    Handles:
      'anthropic/claude-4-sonnet-20250514' → ('anthropic', 'claude-4-sonnet-20250514')
      'openai/gpt-4o'                      → ('openai', 'gpt-4o')
      'ollama/llama3.2'                    → ('ollama', 'llama3.2')
      'bare-model-name'                    → ('default', 'bare-model-name')
    """
    if "/" in model_id:
        provider, name = model_id.split("/", 1)
        return provider, name
    return "default", model_id


class ModelRouterApply(Extension):
    """
    Mid-call extension: replaces call_data["model"] with the router's chosen model.

    Reads: loop_data.params_temporary["router_decision"]
    Writes: call_data["model"]        ← LiteLLMChatWrapper for primary model
            call_data["router_fallback_chain"]  ← list of fallback model IDs
            call_data["router_decision_id"]     ← task_id for correlation
    """

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        call_data: dict = None,
        **kwargs,
    ):
        if not call_data or not self.agent:
            return

        decision = loop_data.params_temporary.get("router_decision")
        # Fallback: chat_model_call_before doesn't receive loop_data from agent.py:817,
        # so the loop_data above is the empty default LoopData(). Read from agent.data.
        if decision is None:
            decision = self.agent.get_data("_router_pending_decision")
        if decision is None:
            return  # router didn't stash a decision; honor the default model

        try:
            from models import get_chat_model
            provider, name = _split_model_id(decision.primary)
            # Note: get_chat_model signature is (provider, name, model_config=None, **kwargs).
            # Passing type=ModelType.CHAT leaks into **kwargs → LiteLLM request body →
            # "Object of type ModelType is not JSON serializable" downstream.
            new_model = get_chat_model(
                provider=provider,
                name=name,
            )
            call_data["model"] = new_model
            call_data["router_fallback_chain"] = decision.fallback
            call_data["router_decision_id"] = decision.task_id
            log.debug(
                json.dumps(
                    {
                        "event": "router_model_applied",
                        "primary": decision.primary,
                        "fallback": decision.fallback,
                        "task_id": decision.task_id,
                    }
                )
            )

            # ----------------------------------------------------------------
            # Phase 43.2: Install execute_with_fallback monkey-patch.
            #
            # Replace call_data["model"].unified_call with a wrapper that
            # iterates [primary] + fallback chain on retryable errors.
            #
            # Wire-site confirmed: agent.py:821 calls
            #   call_data["model"].unified_call(messages=..., ...)
            # Replacing the method on the instance is safe (extra="allow").
            #
            # CRITICAL: wrapper forces a0_retry_attempts=0 to disable Agent Zero's
            # internal retry loop (models.py:508). Otherwise: 3 chain × 3 internal
            # retries = 9 LLM calls instead of 3 (Pitfall 1 from RESEARCH.md).
            # ----------------------------------------------------------------
            try:
                from models import LiteLLMChatWrapper
                if isinstance(call_data["model"], LiteLLMChatWrapper):
                    from core.routing.failover_executor import execute_with_fallback
                    chain = [decision.primary] + (decision.fallback or [])
                    original_unified_call = call_data["model"].unified_call
                    wrapper_instance = call_data["model"]
                    agent_ref = self.agent
                    decision_ref = decision

                    async def _failover_unified_call(**kw):
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

                    call_data["model"].unified_call = _failover_unified_call
                    log.debug(json.dumps({
                        "event": "router_failover_patch_installed",
                        "chain": chain,
                        "task_id": decision.task_id,
                    }))
                else:
                    # Type guard: unexpected model type — skip failover, log warning
                    log.warning(json.dumps({
                        "event": "router_failover_skipped",
                        "reason": "call_data['model'] is not LiteLLMChatWrapper",
                        "actual_type": type(call_data["model"]).__name__,
                    }))
            except Exception as patch_err:
                # Failover patch failure is non-fatal: agent falls back to default model
                # (the call_data["model"] swap already happened above)
                log.warning(json.dumps({
                    "event": "router_failover_patch_error",
                    "error": str(patch_err),
                }))

        except Exception as e:
            log.error(
                json.dumps(
                    {
                        "event": "router_apply_failed",
                        "error": str(e),
                        "primary": decision.primary,
                    }
                )
            )
            # Graceful degradation: call_data["model"] unchanged → agent uses default
