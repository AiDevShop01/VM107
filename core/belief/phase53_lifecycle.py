"""Phase 53 lifecycle: shadow -> proposed -> active -> retired.

Phase 87 Wave 5 — Task 1. Emits governance_action records for downstream
admin UI consumption (Phase 53 pattern).
"""
from __future__ import annotations

from dataclasses import dataclass


REINFORCEMENTS_TO_PROPOSED = 5


@dataclass(frozen=True)
class GovernanceAction:
    belief_id: str
    from_state: str
    to_state: str
    approver_id: str | None
    reason: str | None


def promote_to_proposed(
    belief: dict,
    reinforcement_count: int,
) -> GovernanceAction | None:
    """Auto-promote shadow beliefs once they reach N reinforcements."""
    if (
        belief["lifecycle_state"] == "shadow"
        and reinforcement_count >= REINFORCEMENTS_TO_PROPOSED
    ):
        return GovernanceAction(
            belief_id=str(belief["belief_id"]),
            from_state="shadow",
            to_state="proposed",
            approver_id=None,
            reason=f"auto-promotion at {reinforcement_count} reinforcements",
        )
    return None


def approve_to_active(belief: dict, approver_id: str) -> GovernanceAction:
    """Admin approves a proposed belief -> active."""
    if belief["lifecycle_state"] != "proposed":
        raise ValueError(f"cannot approve from state {belief['lifecycle_state']}")
    return GovernanceAction(
        belief_id=str(belief["belief_id"]),
        from_state="proposed",
        to_state="active",
        approver_id=approver_id,
        reason="admin approval",
    )


def retire_belief(belief: dict, reason: str, approver_id: str) -> GovernanceAction:
    """Retire from any state except already-retired."""
    if belief["lifecycle_state"] == "retired":
        raise ValueError("already retired")
    return GovernanceAction(
        belief_id=str(belief["belief_id"]),
        from_state=belief["lifecycle_state"],
        to_state="retired",
        approver_id=approver_id,
        reason=reason,
    )
