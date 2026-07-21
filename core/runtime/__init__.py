"""core.runtime — Plan 87-14 deploy-gate bridges (additive).

The macro-agent runner scripts import runtime singletons from this namespace:

  * ``from core.runtime import event_store``  — Phase 56 event-store handle
  * ``from core.runtime import llm_router``   — Phase 43 LLM completion router

Both are thin, additive bridges that re-expose *existing* implementations under
the ``core.runtime`` namespace the runners expect. No existing module is
modified. See ``core/events/phase56_client.py`` (event store) and
``core/runtime/llm_router.py`` (LLM completion) for the real code.
"""
from __future__ import annotations

# Phase 56 event store handle — the runners pass this straight through to the
# agent, which uses its module-level ``emit_event`` / ``validate_snapshot_for_replay``.
from core.events import phase56_client as event_store  # noqa: F401

# Phase 43 LLM completion router — submodule exposing ``complete(prompt) -> str``.
from core.runtime import llm_router  # noqa: F401

__all__ = ["event_store", "llm_router"]
