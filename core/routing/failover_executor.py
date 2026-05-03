"""Phase 43.2 — execute_with_fallback wrapper around LiteLLM call execution.

CRITICAL WIRING (research Pitfall 1):
    execute_with_fallback MUST pass a0_retry_attempts=0 to unified_call().
    Otherwise Agent Zero's internal retry loop in models.py:583-590 multiplies
    failover attempts (3 chain × 3 internal retries = 9 LLM calls). The Phase 43.2
    design is "fail fast, switch provider" — internal retry must be disabled
    when running inside the failover wrapper.

    Callers MUST include a0_retry_attempts=0 in call_kwargs OR the wrapper closure
    injects it explicitly (as _router_apply.py does in its wrapper closure).

Wire-site (confirmed by Plan 01 agent.py:821 inspection):
    call_data["model"].unified_call(...) is the call site.
    The monkey-patch in _router_apply.py replaces this method on the instance.

Cross-hook result carrier:
    On success, agent_data["_router_failover_result"] is set to:
        {"model": str, "chain_index": int, "fallback_used": bool, "attempt_count": int}
    Read by _router_log_cost.py (chat) and _20_router_log_cost.py (utility) after-hooks
    to populate CostRecord with the ACTUAL called model (not decision.primary).
    Cleared by after-hooks after read.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import httpx
import litellm.exceptions

from .exceptions import RouterChainExhaustedError

log = logging.getLogger("router.failover")

# LOCKED retryable exception taxonomy (CONTEXT.md decisions section).
# DO NOT add BadRequestError or any of its subclasses (ContextWindowExceededError,
# ContentPolicyViolationError, UnprocessableEntityError) — they MUST re-raise.
RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    # LiteLLM
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.Timeout,
    litellm.exceptions.NotFoundError,
    # stdlib / http
    ConnectionError,
    asyncio.TimeoutError,
    httpx.ConnectError,
)


async def execute_with_fallback(
    call_fn: Callable[..., Awaitable[tuple[str, str]]],
    chain: list[str],
    decision: Any,                                  # RoutingDecision (avoid circular import)
    set_model_name: Callable[[str], None],
    agent_data: dict | None = None,                 # agent.data for cross-hook stash; None in unit tests
    decision_id: str = "",                          # for log correlation
    **call_kwargs: Any,
) -> tuple[str, str]:
    """Execute call_fn iterating chain on retryable errors. Stop on first success or chain exhaustion.

    Args:
        call_fn: Bound unified_call() coroutine; called once per fallback model.
        chain: [primary_model_id, *fallback_model_ids]; iterated in order.
        decision: RoutingDecision instance — wrapper APPENDS reason tags during execution.
                  decision.reason is a mutable list[str].
        set_model_name: Callable that swaps the model on the wrapper instance before each attempt.
                        Called with model_id before each attempt.
        agent_data: agent.data dict for cross-hook carrier. If None (unit tests), stash is skipped.
        decision_id: Correlation ID for structured log events. May be empty.
        **call_kwargs: Forwarded to call_fn.
                       MUST include a0_retry_attempts=0 to disable Agent Zero internal retry
                       (Pitfall 1 — otherwise 3 chain × 3 internal = 9 LLM calls).

    Returns:
        (response, reasoning) tuple from the first successful call_fn invocation.

    Raises:
        RouterChainExhaustedError: All attempts in chain failed with retryable errors.
                                   e.attempts carries exception OBJECTS (not strings).
        Exception: Any non-retryable exception (AuthenticationError, BadRequestError,
                   ContextWindowExceededError, etc.) is re-raised IMMEDIATELY.
                   No fallback attempt is made. attempts list is NOT populated.
        ValueError: If chain is empty.
    """
    if not chain:
        raise ValueError("execute_with_fallback received empty chain")

    attempts: list[dict] = []

    for chain_index, model_id in enumerate(chain):
        # Swap model on the wrapper instance before each attempt.
        set_model_name(model_id)

        try:
            result = await call_fn(**call_kwargs)

        except RETRYABLE_ERRORS as err:
            # Record the failed attempt with the ORIGINAL exception OBJECT (not stringified).
            attempts.append({"model": model_id, "error": err, "chain_index": chain_index})

            # Reason tag: what failed.
            decision.reason.append(f"primary_failed:{type(err).__name__}")

            # Structured log: per-attempt failure (operators can track per-model failure rates).
            log.warning(json.dumps({
                "event": "model_failure",
                "model": model_id,
                "error_class": type(err).__name__,
                "error_message": str(err)[:500],
                "chain_index": chain_index,
                "decision_id": decision_id,
            }))

            # If more entries remain in chain, announce intent to fallback.
            if chain_index + 1 < len(chain):
                decision.reason.append(f"fallback_to:{chain[chain_index + 1]}")
            continue

        except Exception:
            # Non-retryable (AuthenticationError, BadRequestError family, etc.) —
            # re-raise IMMEDIATELY. No fallback attempt. attempts list NOT populated.
            raise

        # ----- Success branch -----
        fallback_used = chain_index > 0
        attempt_count = chain_index + 1

        # Reason tag: success.
        decision.reason.append(f"completed:{model_id}")

        # Structured log: success event.
        log.info(json.dumps({
            "event": "model_success",
            "model": model_id,
            "chain_index": chain_index,
            "fallback_used": fallback_used,
            "attempts_total": attempt_count,
            "decision_id": decision_id,
        }))

        # Stash for after-hooks (Phase 43 cross-hook pattern via agent.data).
        # After-hook reads this to populate CostRecord with the ACTUAL model called.
        # After-hook clears this key after reading.
        if agent_data is not None:
            agent_data["_router_failover_result"] = {
                "model": model_id,
                "chain_index": chain_index,
                "fallback_used": fallback_used,
                "attempt_count": attempt_count,
            }

        return result

    # ----- All attempts exhausted via retryable errors -----
    decision.reason.append("chain_exhausted")

    # Structured log: exhaustion event (always — operators MUST see this).
    log.error(json.dumps({
        "event": "chain_exhausted",
        "attempt_count": len(attempts),
        "attempts": [
            {"model": a["model"], "error_class": type(a["error"]).__name__}
            for a in attempts
        ],
        "decision_id": decision_id,
    }))

    raise RouterChainExhaustedError(attempts)
