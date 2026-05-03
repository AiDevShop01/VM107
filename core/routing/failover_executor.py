"""Phase 43.2 — execute_with_fallback wrapper around LiteLLM call execution.

IMPLEMENTATION DEFERRED TO PLAN 02. This file contains the locked exception
taxonomy + signature contract so downstream test files can import.

CRITICAL WIRING (research Pitfall 1):
    execute_with_fallback MUST pass a0_retry_attempts=0 to unified_call().
    Otherwise Agent Zero's internal retry loop in models.py:583-590 multiplies
    failover attempts (3 chain × 3 internal retries = 9 LLM calls). The Phase 43.2
    design is "fail fast, switch provider" — internal retry must be disabled
    when running inside the failover wrapper.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import httpx
import litellm.exceptions

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
    **call_kwargs: Any,
) -> tuple[str, str]:
    """Execute call_fn iterating chain on retryable errors. (PLAN 02 IMPLEMENTS.)

    Args:
        call_fn: Bound unified_call() coroutine; called once per fallback model.
        chain: [primary_model_id, *fallback_model_ids]; iterated in order.
        decision: RoutingDecision instance — wrapper APPENDS reason tags during execution.
        set_model_name: Callable that swaps the model on the wrapper instance before each attempt.
        **call_kwargs: Forwarded to call_fn (must include a0_retry_attempts=0).

    Returns:
        (response, reasoning) tuple from successful call_fn invocation.

    Raises:
        RouterChainExhaustedError: All attempts failed with retryable errors.
        Exception: Any non-retryable exception is re-raised immediately (no fallback attempt).
    """
    raise NotImplementedError("Implemented in Plan 02 — Wave 1")
