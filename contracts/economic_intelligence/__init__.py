"""Economic Intelligence contracts — Phase 94 Wave 0.

Canonical Pydantic v2 contracts for the Macro Situation Room. Vendored copies
live under VM100/VM102/VM107 (rsync'd from this source-of-truth — never edit
the vendored copies). Every model is frozen + extra='forbid' and carries
schema_version (monotonic integer string).
"""

from .alerts import Alert, AlertsSection
from .base_section import BaseSection, SectionStatus
from .central_bank import (
    CentralBankSection,
    CentralBankStance,
    CentralBankStatement,
)
from .country_card import CountryCardSection
from .cross_asset import AssetLevel, CrossAssetSection
from .domain import Domain, DomainEdge, Driver, IndicatorRef
from .events import EconomicEvent, EventSeverity, EventType
from .executive_summary import ExecutiveSummarySection
from .forecast import ForecastEntry, ForecastSection
from .pillars import Pillar, PillarName, PillarsSection, PillarState
from .provenance import ProvenanceObject
from .relationships import Relationship, RelationshipSection
from .research import ResearchItem, ResearchSection
from .snapshot import EconomicSnapshot, SnapshotHealth
from .specialist_response import SpecialistResponse
from .themes import Theme, ThemeMonitorSection, ThemeState
from .timeline import TimelineEntry, TimelineSection

__all__ = [
    # Alerts
    "Alert",
    "AlertsSection",
    # Base
    "BaseSection",
    "SectionStatus",
    # Central bank
    "CentralBankSection",
    "CentralBankStance",
    "CentralBankStatement",
    # Country
    "CountryCardSection",
    # Cross-asset
    "AssetLevel",
    "CrossAssetSection",
    # Domain (Phase 95)
    "Domain",
    "DomainEdge",
    "Driver",
    "IndicatorRef",
    # Events
    "EconomicEvent",
    "EventSeverity",
    "EventType",
    # Executive summary
    "ExecutiveSummarySection",
    # Forecast
    "ForecastEntry",
    "ForecastSection",
    # Pillars
    "Pillar",
    "PillarName",
    "PillarsSection",
    "PillarState",
    # Provenance
    "ProvenanceObject",
    # Relationships
    "Relationship",
    "RelationshipSection",
    # Research
    "ResearchItem",
    "ResearchSection",
    # Snapshot
    "EconomicSnapshot",
    "SnapshotHealth",
    # Specialist
    "SpecialistResponse",
    # Themes
    "Theme",
    "ThemeMonitorSection",
    "ThemeState",
    # Timeline
    "TimelineEntry",
    "TimelineSection",
]
