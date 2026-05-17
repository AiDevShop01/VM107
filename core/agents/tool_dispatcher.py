"""Phase 47.6 LD-6c — tool dispatch interception.

The dispatcher is the ONLY surface that may invoke a capability.
EVERY invocation flows through here. EVERY refusal (stub/experimental
capability invocation) writes a CapabilityRefusalEvent to the active
envelope's capability_refusal_log.

The refusal cascade (Phase 47.3 ConfidenceAdjustment) reads from THIS log,
not from the introspection log (B2 fix per CONTEXT.md decision #6c).

B2 architectural invariant:
- lookup_capability.lookup() → writes to capability_introspection_log ONLY
- dispatch_tool() → writes to capability_refusal_log ONLY (on refusal)
- These are two separate lists. The cascade reads from capability_refusal_log.

Public API:
    dispatch_tool(tool_name: str, kwargs: dict) -> Any
        Returns the tool result on success, or the structured refusal payload
        (dict) on refusal. The refusal payload is what the LLM sees as a tool-error.

    class UnknownToolError(Exception)
        Raised when the tool_name is not found in the registry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fingpt_core.contracts.capability_registry import (
    CapabilityRefusalEvent,
)
from core.registry.capability_registry import CapabilityRegistry
from core.agents.envelope_context import current_envelope
from core.agents.refusal_cascade import (
    should_refuse,
    build_refusal_payload,
    IMPACT_TO_CONFIDENCE_DELTA,
)


class UnknownToolError(Exception):
    """Raised when dispatch_tool() cannot find the requested tool in the registry."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Unknown tool: {tool_name!r} — not registered in capability registry")
        self.tool_name = tool_name


def dispatch_tool(tool_name: str, kwargs: dict) -> Any:
    """Invoke `tool_name` after checking the registry for refusal.

    This is the SOLE entry point for all capability invocations. Every tool
    call from the agent runtime MUST flow through here to enforce LD-6c.

    Flow:
    1. Look up capability in registry.
    2. If not found → raise UnknownToolError.
    3. If should_refuse(summary) → build refusal payload, append CapabilityRefusalEvent
       to envelope.capability_refusal_log, return refusal payload.
    4. If invokable (real / deprecated) → call _invoke_tool_impl(tool_name, kwargs).

    Args:
        tool_name: The capability id to invoke (must match registry id).
        kwargs: Tool keyword arguments to pass to the implementation.

    Returns:
        Tool result dict on successful invocation, OR structured refusal payload
        dict (with status="capability_unavailable") on refusal.

    Raises:
        UnknownToolError: If tool_name is not registered.
    """
    reg = CapabilityRegistry.get()
    summary = reg.lookup(tool_name)

    if summary is None:
        # Unknown tool — not a refusal; surface a different error path
        raise UnknownToolError(tool_name)

    if should_refuse(summary):
        # LD-6c: stub or experimental → never invoke
        envelope = current_envelope.get()
        if envelope is not None:
            event = CapabilityRefusalEvent(
                capability_id=summary.id,
                registry_status=summary.status.value,  # "stub" or "experimental"
                impact_on_decision=summary.impact_on_decision.value,  # "HIGH"|"MEDIUM"|"LOW"
                planned_phase=summary.location.get("planned_phase"),
                impact_on_reasoning="partial_context_loss",
                auto_confidence_adjustment=IMPACT_TO_CONFIDENCE_DELTA[
                    summary.impact_on_decision.value
                ],
                registry_snapshot_hash=reg.snapshot_hash,
                occurred_at=datetime.now(timezone.utc),
                reasoning_context_id=str(getattr(envelope, "envelope_id", "unknown") or "unknown"),
            )
            # B2: SOLE writer to capability_refusal_log (invocation attempts only)
            envelope.capability_refusal_log.append(event)

        return build_refusal_payload(summary)

    # Real / deprecated: invoke normally.
    # (Deprecated may log a warning via a separate mechanism; not in this phase.)
    return _invoke_tool_impl(tool_name, kwargs)


def _invoke_tool_impl(tool_name: str, kwargs: dict) -> Any:
    """Execute a non-refused tool.

    V1 placeholder: in production this would dispatch to the actual tool
    implementation via the tool registry. For Phase 47.6 scope, the dispatcher
    architecture is what matters — the concrete tool routing is handled by
    the existing tool_scope.py / AgentRunner infrastructure.

    This function is intentionally minimal and mockable in tests.
    """
    raise NotImplementedError(
        f"_invoke_tool_impl for {tool_name!r} not wired in Phase 47.6 scope. "
        "The existing tool execution infrastructure handles real dispatch. "
        "This function exists to make the refusal gate testable and to mark "
        "the boundary between 'refused' and 'invokable' in the dispatcher flow."
    )
