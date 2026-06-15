"""Phase 86 Plan 07 — Thin LLM call wrapper for standalone event-driven agents.

This module provides a synchronous `call_llm(prompt: str) -> str` wrapper
for standalone single-emit-terminate agents that do NOT run inside the Agent Zero
profile loop (e.g. macro_historical_analyst).

Design constraints:
- No hardcoded model names or URLs — all config via env vars (_required pattern)
- Uses litellm.completion (allowlisted via models.py) routed through the same
  LiteLLM gateway as the rest of VM107
- Synchronous; callers that need async should run in executor
- No fallback defaults — fail-fast on missing config (CLAUDE.md env-driven rule)

Env vars required:
- LLM_MODEL: litellm model string, e.g. "openai/gpt-4o-mini" or "anthropic/claude-3-haiku-20240307"
- LLM_API_KEY: API key for the chosen provider (passed to litellm as api_key)

Optional:
- LLM_API_BASE: Base URL override for LiteLLM (e.g. for proxies / litellm proxy server)
- LLM_MAX_TOKENS: Max tokens in response (default 512 — sufficient for <=50-word narratives)

This module is NOT the path for multi-iteration agent loops — those use the Agent Zero
profile + extension system (Phase 85 B1 writer).
"""
from __future__ import annotations

import os

import litellm


def _required(key: str) -> str:
    """Return env var value or raise RuntimeError. No fallback defaults (CLAUDE.md rule)."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast (env-driven-no-fallbacks lock)"
        )
    return v


def call_llm(prompt: str) -> str:
    """Make a single synchronous LLM call and return the text response.

    Used by event-driven single-emit-terminate agents (macro_historical_analyst).
    NOT for multi-iteration loops — use Agent Zero profile system for those.

    Args:
        prompt: The full prompt string to send to the LLM.

    Returns:
        The LLM text response as a plain string.

    Raises:
        RuntimeError: If required env vars (LLM_MODEL, LLM_API_KEY) are not set.
        litellm.exceptions.AuthenticationError: If API key is invalid.
        litellm.exceptions.BadRequestError: If the model rejects the request.
    """
    model = _required("LLM_MODEL")
    api_key = _required("LLM_API_KEY")
    api_base = os.environ.get("LLM_API_BASE")  # Optional — None means use provider default
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "512"))

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "api_key": api_key,
        "max_tokens": max_tokens,
    }
    if api_base:
        kwargs["api_base"] = api_base

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content or ""
