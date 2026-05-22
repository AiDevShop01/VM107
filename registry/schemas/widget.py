"""Pydantic schema for `widget` capability registry entries.

Phase 65 introduces the `widget` capability type as part of the Phase 47.6
mandatory consolidation. Mission Control panels (ribbon, narrative, intel
feed, trader-state strip, agent ticker, MID grid widgets) all carry a
matching `VM107/registry/widget/mission.*.yaml` entry validated by this
schema (REQ-65-9).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class WidgetCapability(BaseModel):
    """Capability registry entry for a UI widget."""

    id: str
    type: Literal["widget"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str  # ISO date (YYYY-MM-DD)

    name: str
    category: str
    description: str

    owner_vm: str
    primary_workflow: str
    priority_level: Literal["P1", "P2", "P3", "P4"]

    supported_states: list[Literal["pre", "open", "mid", "close"]]
    supported_devices: list[Literal["desktop", "mobile", "tablet"]] = Field(
        default_factory=list
    )
    data_freshness_type: Literal[
        "real_time", "near_real_time", "polled", "static"
    ]

    primary_data_contracts: list[str] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)

    events_consumed: list[str] = Field(default_factory=list)
    events_emitted: list[str] = Field(default_factory=list)

    ai_capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

    caching_strategy: Optional[dict] = None
    error_states: list[str] = Field(default_factory=list)

    # Phase-66+ demo flag: True when the widget renders `[DEMO]` chips because
    # its real data source is not yet shipped.
    phase_demo_flag: bool = False

    location: dict
    emitted_by: Optional[str] = None

    related_capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    hard_scoped: bool = True
    impact_on_decision: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    allowed_agent_profiles: list[str] = Field(default_factory=list)
    deprecated: bool = False

    # ─── Forward-compat fields (Phases 71 / 74 / 76 / 47.6) ─────────────────
    # These are populated explicitly on every Phase-65 widget YAML so the
    # Phase 47.6 schema validator passes today and Phases 71/74/76 can read
    # them as-is without a retroactive YAML migration.
    #
    # evidence_drawer.supported (Phase 71)  — does <EvidenceDrawer/> attach?
    # conversation_modes        (Phase 71)  — which <ConversationalAI/> modes
    #                                          this panel accepts.
    # notification_channels_consumed (Phase 74) — which NotificationChannel
    #                                          stream this widget reacts to.
    # freshness_class           (Phase 76)  — FreshnessClass for the widget's
    #                                          primary data.
    evidence_drawer: dict = Field(default_factory=lambda: {"supported": False})
    conversation_modes: list[
        Literal[
            "pre-trade",
            "macro",
            "execution",
            "reflection",
            "research",
            "strategy",
        ]
    ] = Field(default_factory=list)
    notification_channels_consumed: list[
        Literal[
            "opportunities",
            "invalidation",
            "macro",
            "risk",
            "behavioral",
        ]
    ] = Field(default_factory=list)
    freshness_class: list[
        Literal[
            "REAL_TIME",
            "NEAR_REAL_TIME",
            "AI_GENERATED",
            "SESSION_CACHED",
            "DAILY",
            "BACKFILL",
            "STATIC",
        ]
    ] = Field(default_factory=list)
