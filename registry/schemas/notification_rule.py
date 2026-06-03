"""Pydantic schema for ``notification_rule`` capability registry entries.

Phase 74 ships 11 seed rules that map DomainEvent → Channel + Priority.
Rules are YAML-seeded (capability registry) and DB-backed at runtime.
The catch-all ``default_to_system`` rule (precedence: 9999, terminal: true)
ensures nothing is silently dropped.

Boot-validated by the Phase 47.6 loader.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ChannelValue = Literal[
    "opportunities", "invalidation", "macro", "risk", "behavioral", "system"
]
PriorityValue = Literal["P1", "P2", "P3", "P4"]
DismissibilityValue = Literal[
    "fully_dismissible", "dismissible", "acknowledge_required"
]


class NotificationRuleCapability(BaseModel):
    """Capability registry entry for a NotificationRule routing rule.

    Rules are evaluated in ascending ``precedence`` order.  The first rule
    that matches (condition_expr == True) wins; subsequent rules are skipped
    UNLESS ``terminal: False`` (pass-through rules are rare).

    The catch-all ``default_to_system`` rule has ``precedence: 9999`` and
    ``terminal: true`` — it is always last in the chain.
    """

    id: str
    type: Literal["notification_rule"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str  # ISO date — quote in YAML

    description: str

    # Source event / observation matcher.
    # "*" = catch-all (only valid for default_to_system).
    trigger_event_type: str

    # Target channel for matched notifications.
    channel: ChannelValue

    # Resulting priority.
    priority: PriorityValue

    # Python-evaluable expression string (evaluated against Observation fields).
    # "True" = always match (catch-all).
    condition_expr: str

    # Dismissibility profile for the resulting notification.
    dismissibility_profile: DismissibilityValue = "fully_dismissible"

    # Evaluation order (lower = higher priority; 9999 = last / catch-all).
    precedence: int = 100

    # When True: engine stops evaluating further rules after this one fires.
    terminal: bool = True

    # Whether this rule is actively enforced at runtime.
    active: bool = True

    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
