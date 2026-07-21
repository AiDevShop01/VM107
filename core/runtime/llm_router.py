"""Phase 43 LLM completion router bridge (Plan 87-14, additive).

The macro-agent runners import ``from core.runtime import llm_router`` and the
agents call ``llm_router.complete(prompt) -> str`` (see
``agents/macro_story_tracker/agent.py``). This module bridges that one-method
contract to the existing synchronous ``services.llm_client.call_llm`` primitive
(litellm-backed, env-configured via ``LLM_MODEL`` / ``LLM_API_KEY``).

No existing module is modified — this only exposes the expected name/method.
"""
from __future__ import annotations


def complete(prompt: str) -> str:
    """Make a single synchronous LLM completion and return the text response.

    Delegates to ``services.llm_client.call_llm``. The import is lazy so that
    merely importing ``core.runtime`` (e.g. for ``event_store``) never forces the
    litellm/env-var dependency to resolve at import time — it resolves only when a
    completion is actually requested.
    """
    from services.llm_client import call_llm

    return call_llm(prompt)
