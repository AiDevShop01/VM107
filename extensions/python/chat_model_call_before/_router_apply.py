"""Phase 43 router apply — Step 2 of two-extension swap pattern.

Reads stashed RoutingDecision from loop_data.params_temporary, mutates
call_data["model"] to the chosen LiteLLMChatWrapper instance, and attaches
the fallback chain to call_data for reference by other extensions.

RESEARCH.md Open Question 2 — RESOLVED:
  LiteLLMChatWrapper.unified_call() does NOT accept a fallbacks= kwarg. It
  constructs its own acompletion() call with a custom retry loop (see models.py
  lines 473-600). The LiteLLM completion() fallbacks= kwarg is NOT threaded
  through unified_call(). Therefore:
  - We mutate call_data["model"] to the primary LiteLLMChatWrapper.
  - We attach call_data["router_fallback_chain"] with the ordered model IDs.
  - Provider-level failover relies on LiteLLM's existing retry (max_retries
    from a0_retry_attempts env/config). The router's secondary/local models
    serve as a semantic fallback — future work can wire explicit multi-model
    retry if provider failover proves insufficient.
  - This is documented in 43-05-SUMMARY.md under LiteLLM Fallback API Finding.

Graceful no-op when:
  - call_data is None
  - self.agent is None
  - router_decision not in params_temporary (router skipped / init failed)
  - get_chat_model() raises (unknown provider/model: log, skip swap)
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
