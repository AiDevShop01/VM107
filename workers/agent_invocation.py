"""Phase 85.1 agent invocation helper for the task dispatcher.

Public mirror of ``core/agents/invocation._call_subordinate_sync``.
Created as a SEPARATE module (not importing from invocation) to prevent the
Pitfall 7 import-cycle that arises because:

  invocation.py is at module top imported by many core modules.
  agent.py imports core modules.
  If workers/agent_invocation.py imported from core.agents.invocation at
  module top, importing the workers package would trigger agent.py → core →
  invocation → (already importing) cycle, which is a circular import error.

Resolution: module-level sentinels are set to None by default (patchable by
tests).  Tests can patch ``VM107.workers.agent_invocation.AgentContext``
BEFORE calling ``_dispatch_agent_sync`` and the function will use the patched
version via globals() / module-scope lookup (NOT a local import rebinding).

Source pattern: VM107/core/agents/invocation.py lines 133–196
    (``_call_subordinate_sync``).

Pitfall 2 contract (slot-30 router + slot-20 B1 write):
    Both the slot-30 router (fail-fast) and the slot-20 B1 write filter on
    ``profile_id`` as stored in ``sub.data``, NOT on ``config.profile``.
    Therefore ``sub.set_data("profile_id", profile_id)`` MUST be called
    BEFORE ``sub.hist_add_user_message(...)`` BEFORE ``asyncio.run(sub.monologue())``.
    Violating this order causes the router to silently drop the message.

Test-patchable surface:
    ``VM107.workers.agent_invocation.AgentContext`` — module-level sentinel.
    Tests patch it before calling _dispatch_agent_sync; the function sees the
    patched value via module globals.
    ``VM107.workers.agent_invocation._dispatch_agent_sync`` — patch the
    whole function in integration tests to avoid any Agent Zero dependency.

DO NOT add ``from core.agents.invocation import _call_subordinate_sync`` at
module top — that defeats Pitfall 7 protection (see RESEARCH.md Pitfall 7).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level sentinels — populated lazily on first real call.
# Tests can patch these directly:
#   patch("VM107.workers.agent_invocation.AgentContext", mock_ac)
#   patch("VM107.workers.agent_invocation.UserMessage", mock_um)
#   patch("VM107.workers.agent_invocation.initialize_agent", mock_ia)
# If a sentinel is patched to a non-None value, lazy-loading is skipped and
# the patched value is used instead.
# ---------------------------------------------------------------------------
AgentContext: Any = None  # type: ignore[assignment]
UserMessage: Any = None  # type: ignore[assignment]
initialize_agent: Any = None  # type: ignore[assignment]


def _ensure_agent_runtime() -> None:
    """Lazy-load Agent Zero runtime modules into module-level sentinels.

    Only runs the import if ``AgentContext`` is still None (not patched).
    Tests set ``AgentContext`` before calling _dispatch_agent_sync, so this
    function becomes a no-op in test contexts.

    Raises:
        RuntimeError: If Agent Zero runtime is unavailable (agent.py / initialize.py).
    """
    global AgentContext, UserMessage, initialize_agent

    if AgentContext is not None:
        # Already loaded or test-patched — nothing to do
        return

    try:
        from agent import AgentContext as _Ac, UserMessage as _Um  # type: ignore[import]
        from initialize import initialize_agent as _ia  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "_dispatch_agent_sync requires Agent Zero runtime (agent.py + initialize.py). "
            "In tests, patch VM107.workers.agent_invocation.AgentContext (and optionally "
            "UserMessage, initialize_agent) BEFORE calling _dispatch_agent_sync, or patch "
            "_dispatch_agent_sync directly to skip Agent Zero entirely."
        ) from exc

    AgentContext = _Ac
    UserMessage = _Um
    initialize_agent = _ia


def _dispatch_agent_sync(
    profile_id: str,
    user_message: str,
) -> tuple[str, dict]:
    """Invoke a subordinate Agent Zero instance for the given profile and return output.

    Synchronous wrapper around Agent Zero's async monologue.  Safe to call from
    a worker thread because ``asyncio.run()`` creates a fresh event loop in the
    calling thread.

    Args:
        profile_id: Agent profile identifier (e.g. "vm107.macro_release_analyst").
        user_message: The prompt / instruction to deliver to the subordinate agent.

    Returns:
        (raw_output, telemetry) where:
          raw_output — the agent's raw text response (usually JSON).
          telemetry  — dict with keys: model_used, reason_chain, cost,
                       fallback_used, b1_artifact_id.

    Raises:
        RuntimeError: If Agent Zero bootstrap fails (agent.py or initialize.py
                      not importable).  In unit tests, patch ``AgentContext`` at
                      the module level or patch this function directly.

    PITFALL 2 (slot-30 router + slot-20 B1 write):
        ``sub.set_data("profile_id", profile_id)`` is called BEFORE
        ``sub.hist_add_user_message(...)`` BEFORE ``asyncio.run(sub.monologue())``.
        This ordering is validated by
        ``test_dispatch_agent_sync_sets_profile_id_before_monologue``.
    """
    # Ensure runtime modules are loaded (no-op if already loaded or patched).
    _ensure_agent_runtime()

    # Build a minimal subordinate AgentContext using Agent Zero's profile system.
    # Mirrors core/agents/invocation._call_subordinate_sync (lines 166-195).

    # Initialize config if initialize_agent is available (production path).
    # In some test contexts only AgentContext is patched; initialize_agent may be None.
    if initialize_agent is not None:
        config = initialize_agent()
        config.profile = profile_id  # override the default profile
    else:
        config = None  # test context — not needed when sub is provided via get()

    ctx_name = f"dispatch_{profile_id}_{uuid.uuid4().hex[:8]}"

    # Try to retrieve sub-agent via AgentContext.get (static lookup).
    # In tests: mock_agent_ctx.get.return_value == mock_sub → returns the mock directly.
    # In production: AgentContext.get(ctx_name) returns None (no context registered
    #   yet with that name-as-id), so we fall through to create a new context.
    sub = AgentContext.get(ctx_name)  # type: ignore[misc]
    if sub is None:
        # Production path: create a new AgentContext and use its inner Agent.
        ctx = AgentContext(config=config, name=ctx_name)  # type: ignore[misc]
        sub = ctx.agent0  # AgentContext.__init__ creates agent0 internally

    # -------------------------------------------------------------------
    # PITFALL 2 CONTRACT: set_data("profile_id") MUST precede both
    # hist_add_user_message AND asyncio.run(monologue).
    # slot-30 router (fail-fast) + slot-20 B1 write both filter on
    # sub.data["profile_id"], not config.profile.
    # -------------------------------------------------------------------
    sub.set_data("profile_id", profile_id)

    # Inject routing agent_id for affinity map lookup (optional — don't abort dispatch).
    try:
        from core.agents.tool_scope import resolve_agent_id_from_profile  # type: ignore[import]
        sub.data["agent_id"] = resolve_agent_id_from_profile(profile_id)
    except Exception:  # noqa: BLE001
        # tool_scope is optional; silently skip if unavailable
        pass

    # Add the user message to subordinate's history, then run its monologue.
    # Agent.monologue() takes no arguments — the message must already be in history.
    # If UserMessage is None (some test contexts patch only AgentContext), pass raw str.
    msg = UserMessage(message=user_message, attachments=[]) if UserMessage is not None else user_message  # type: ignore[misc]
    sub.hist_add_user_message(msg)

    # asyncio.run() is safe here: called from a worker thread with no existing event loop.
    raw: Any = asyncio.run(sub.monologue())

    # Capture router telemetry after monologue (before after-hooks clear it).
    # Keys mirror the Phase 43.2 _router_log_cost.py carrier pattern.
    telemetry: dict = {
        "model_used": sub.data.get("_router_model_used", "unknown"),
        "reason_chain": sub.data.get("_router_reason_chain", []),
        "cost": sub.data.get("_router_cost_record", {}),
        "fallback_used": sub.data.get("_router_fallback_used", False),
        "b1_artifact_id": sub.data.get("last_b1_artifact_id"),
    }

    return raw, telemetry
