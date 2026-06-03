"""Pydantic schema for ``notification_channel`` capability registry entries.

Phase 74 introduces 6 notification channels:
  opportunities | invalidation | macro | risk | behavioral | system

Each channel encodes its anti-noise batching rules (CONTEXT.md §16),
lifecycle-state guards (§17), and dismissibility defaults (§15).
Boot-validated by the Phase 47.6 loader.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ChannelId = Literal[
    "opportunities", "invalidation", "macro", "risk", "behavioral", "system"
]
PriorityKey = Literal["P1", "P2", "P3", "P4"]
DismissibilityValue = Literal[
    "fully_dismissible", "dismissible", "acknowledge_required"
]
GuardAction = Literal["suppress", "warn_and_deliver", "deliver"]
DeliveryMode = Literal["in_app", "push", "history", "silent"]


class NotificationChannelCapability(BaseModel):
    """Capability registry entry for a notification channel."""

    id: ChannelId
    type: Literal["notification_channel"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str  # ISO date — quote in YAML to defeat auto-coerce

    display_name: str
    badge_color: str  # CSS colour token, e.g. "slate-500"
    description: str

    # Anti-noise batching per priority (CONTEXT.md §16).
    # False = immediate / no batch; True = use batch_window_seconds.
    batchable_by_priority: dict[str, bool]  # P1/P2/P3/P4 → bool

    # Batch window in seconds per priority (only relevant when batchable=True).
    batch_window_seconds_by_priority: dict[str, Optional[int]] = Field(
        default_factory=dict
    )

    # Default dismissibility for notifications in this channel.
    dismissibility_default: DismissibilityValue

    # Per-priority override for dismissibility (e.g. Risk CRITICAL → acknowledge_required).
    dismissibility_by_priority: dict[str, DismissibilityValue] = Field(
        default_factory=dict
    )

    # Lifecycle states that suppress delivery (e.g. behavioral suppressed during
    # ACTIVE_SUPERVISION).  Empty list = never suppressed.
    lifecycle_state_guard: list[str] = Field(default_factory=list)

    # Per-priority action when lifecycle guard is active.
    guard_action_by_priority: dict[str, GuardAction] = Field(default_factory=dict)

    # Which priorities bypass the Quiet preset (P1 risk and P1 system are the
    # only combinations that ignore user's Quiet setting).
    quiet_preset_bypass_priorities: list[str] = Field(default_factory=list)

    # Default delivery modes (in_app always on; push opt-in; history = bell + page).
    default_delivery: list[DeliveryMode] = Field(default_factory=list)

    # For system channel: P1 auto-escalation trigger list.
    auto_escalate_to_p1_triggers: list[str] = Field(default_factory=list)

    # Default priority for unclassified notifications landing in this channel.
    default_priority: Optional[str] = None

    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
