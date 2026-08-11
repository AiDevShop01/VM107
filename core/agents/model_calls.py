"""Phase 138 (P6 / F3 Seam 2) — model calls extracted from agent.py:772-856.

Pure move: Agent.call_utility_model (agent.py:772-812) + Agent.call_chat_model
(agent.py:814-856) bodies, `self` -> `agent`. Behavior identical (D-03).

Both fns read the rate limiter / context / config OFF the passed `agent` (no module
state) and fire the `*_model_call_before/after` extension hooks with the AGENT
instance — Agent keeps thin async @extension.extensible delegators so the B5
getattr probe surface (core/b5/rubric_scorer.py, response_self_check_hook.py) and
the internal call_chat_model caller (agent.py:480) are unchanged (SC-3).

Public API:
    async call_utility_model(agent, system, message, callback=None, background=False) -> str
    async call_chat_model(agent, messages, response_callback=None,
                          reasoning_callback=None, background=False,
                          explicit_caching=True) -> tuple[str, str]
"""
from __future__ import annotations

from helpers import extension


async def call_utility_model(agent, system, message, callback=None, background=False):
    model = agent.get_utility_model()

    # call extensions
    call_data = {
        "model": model,
        "system": system,
        "message": message,
        "callback": callback,
        "background": background,
    }
    await extension.call_extensions_async(
        "util_model_call_before", agent, call_data=call_data
    )

    # propagate stream to callback if set
    async def stream_callback(chunk: str, total: str):
        if call_data["callback"]:
            await call_data["callback"](chunk)

    response, _reasoning = await call_data["model"].unified_call(
        system_message=call_data["system"],
        user_message=call_data["message"],
        response_callback=stream_callback if call_data["callback"] else None,
        rate_limiter_callback=(
            agent.rate_limiter_callback if not call_data["background"] else None
        ),
    )

    await extension.call_extensions_async(
        "util_model_call_after", agent, call_data=call_data, response=response
    )

    return response


async def call_chat_model(
    agent,
    messages,
    response_callback=None,
    reasoning_callback=None,
    background=False,
    explicit_caching=True,
):
    response = ""

    # model class
    model = agent.get_chat_model()

    # call extensions before
    call_data = {
        "model": model,
        "messages": messages,
        "response_callback": response_callback,
        "reasoning_callback": reasoning_callback,
        "background": background,
        "explicit_caching": explicit_caching,
    }
    await extension.call_extensions_async(
        "chat_model_call_before", agent, call_data=call_data
    )

    # call model
    response, reasoning = await call_data["model"].unified_call(
        messages=call_data["messages"],
        reasoning_callback=call_data["reasoning_callback"],
        response_callback=call_data["response_callback"],
        rate_limiter_callback=(
            agent.rate_limiter_callback if not call_data["background"] else None
        ),
        explicit_caching=call_data["explicit_caching"],
    )

    await extension.call_extensions_async(
        "chat_model_call_after", agent, call_data=call_data, response=response, reasoning=reasoning
    )

    return response, reasoning
