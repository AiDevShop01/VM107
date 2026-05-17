"""Phase 47.6 LD-6c — capability refusal cascade.

Builds the structured refusal payload returned to the LLM when it attempts
to INVOKE a stub or experimental capability via the tool dispatcher.

B2 architectural invariant (CONTEXT.md decision #6c):
    The refusal cascade ONLY reads from envelope.capability_refusal_log
    (invocation attempts). It NEVER reads from envelope.capability_introspection_log
    (mere introspection). Introspecting a stub does NOT penalize confidence.
    Only INVOKING a stub does.

IMPACT_TO_CONFIDENCE_DELTA mapping (per CONTEXT.md decision #6c example):
    HIGH   → -15
    MEDIUM → -10
    LOW    → -5

Sole public API:
    should_refuse(summary: CapabilitySummary) -> bool
    build_refusal_payload(summary: CapabilitySummary) -> dict
    _emit_capability_unavailable_adjustments(envelope) -> list[ConfidenceAdjustment]
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fingpt_core.contracts.capability_registry import (
    CapabilitySummary,
    CapabilityRefusalEvent,
    CapabilityStatus,
)

if TYPE_CHECKING:
    pass  # avoid circular imports; ConfidenceAdjustment imported inside function

# Per CONTEXT.md decision #6c example: stub HIGH = -15
IMPACT_TO_CONFIDENCE_DELTA: dict[str, int] = {
    "HIGH": -15,
    "MEDIUM": -10,
    "LOW": -5,
}

# LD-6c: stub and experimental are NEVER invokable in V1
REFUSAL_STATUSES: frozenset[CapabilityStatus] = frozenset({
    CapabilityStatus.STUB,
    CapabilityStatus.EXPERIMENTAL,
})


def should_refuse(summary: CapabilitySummary) -> bool:
    """LD-6c: return True if this capability must be refused on invocation.

    Only stub and experimental capabilities are refused in V1.
    Real and deprecated capabilities are invokable (deprecated may log a warning).

    Args:
        summary: CapabilitySummary from the registry.

    Returns:
        True if the invocation must be refused; False otherwise.
    """
    return summary.status in REFUSAL_STATUSES


def _planned_phase_from_summary(summary: CapabilitySummary) -> str | None:
    """Extract planned_phase from the summary's location dict (may be None)."""
    return summary.location.get("planned_phase")


def build_refusal_payload(summary: CapabilitySummary) -> dict:
    """Build the LD-6c locked refusal payload returned to the LLM as a tool-error.

    This is the structured response the agent receives when it attempts to
    invoke a stub or experimental capability. The shape is locked per
    CONTEXT.md decision #6c — never change the key names without a phase decision.

    Args:
        summary: CapabilitySummary of the refused capability.

    Returns:
        dict with keys: status, capability_id, registry_status, planned_phase,
                        impact_on_reasoning, auto_confidence_adjustment.
    """
    impact_key = summary.impact_on_decision.value  # "HIGH" | "MEDIUM" | "LOW"
    return {
        "status": "capability_unavailable",
        "capability_id": summary.id,
        "registry_status": summary.status.value,
        "planned_phase": _planned_phase_from_summary(summary),
        "impact_on_reasoning": "partial_context_loss",
        "auto_confidence_adjustment": IMPACT_TO_CONFIDENCE_DELTA[impact_key],
    }


def _emit_capability_unavailable_adjustments(envelope) -> list:
    """LD-6c cascade — produce ConfidenceAdjustment rows from invocation attempts only.

    B2 FIX: Iterates envelope.capability_refusal_log ONLY (NEVER capability_introspection_log).
    Each CapabilityRefusalEvent in the refusal log becomes one ConfidenceAdjustment.
    Mere introspection of stubs does NOT penalize.

    Args:
        envelope: AgentEnvelope with capability_refusal_log populated by tool_dispatcher.

    Returns:
        list[ConfidenceAdjustment] — one row per refusal event (may be empty).

    Note: This function does NOT persist the adjustments — it returns them for
    the caller (evaluation_runner._persist or similar) to attach to the evaluation.
    Phase 47.3's ConfidenceAdjustment rows are the consumer of this output.
    """
    from fingpt_core.contracts.agents.pre_trade_evaluation import ConfidenceAdjustment

    adjustments = []
    for event in envelope.capability_refusal_log:
        assert isinstance(event, CapabilityRefusalEvent), (
            f"B2 invariant: refusal_log must contain only CapabilityRefusalEvent, got {type(event)}"
        )
        adjustments.append(ConfidenceAdjustment(
            reason=f"capability_unavailable:{event.capability_id}",
            capability_id=event.capability_id,
            impact=event.auto_confidence_adjustment,
            impact_tier=event.impact_on_decision,
        ))
    return adjustments
