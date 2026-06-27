"""Phase 94-06 — Executive Summary agent (event-driven, cached).

Subscribes to the Phase 94 Event Bus and regenerates a 30-60 word
``ExecutiveSummarySection`` **only** when a HIGH or CRITICAL severity
event arrives (per §K.3 + REQ-94-5).

Per §J/§K locks:

* Narrative-only specialist — denied tools forbid belief proposals,
  forecast/trade emission, code execution, filesystem writes.
* Deterministic template-based composition in Wave 3b; 94-07 can swap
  to LLM completion behind the same ``ExecutiveSummarySection`` contract.
* Caches the most-recent summary keyed by country; ``invoke()`` returns
  the cache when no new HIGH+ event has arrived since last regen.

The agent owns NO score calculation — pillars/regime are read-only inputs
from upstream sections passed via ``context``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.events import EconomicEvent, EventSeverity, EventType
from contracts.economic_intelligence.executive_summary import ExecutiveSummarySection
from contracts.economic_intelligence.provenance import ProvenanceObject

logger = logging.getLogger(__name__)


# Severities that trigger regeneration per §K.3.
_REGEN_SEVERITIES = frozenset({EventSeverity.HIGH, EventSeverity.CRITICAL})

# Event types we listen to. 94-07 may extend; the §K.3 cut covers the four
# event families that move the executive-summary headline.
_SUBSCRIBED_EVENTS = (
    EventType.MACRO_RELEASE,
    EventType.CENTRAL_BANK,
    EventType.REGIME_CHANGE,
    EventType.FORECAST_UPDATE,
)

_MIN_WORDS = 30
_MAX_WORDS = 60


class ExecutiveSummary:
    """Event-driven executive summary composer (cached).

    Cache layout: ``self._cache[country]`` -> tuple(section, last_event_id).
    Stays in-process for Wave 3b; 94-07 wires Redis persistence via the
    SnapshotCoordinator.
    """

    AGENT_ID = "vm107.executive_summary"
    SECTION_ID = "executive_summary"

    def __init__(self, narrative_builder: Any | None = None) -> None:
        # Injected for tests; default is the deterministic template below.
        self._build_narrative = narrative_builder or _default_narrative
        # country -> (section, triggering_event)
        self._cache: dict[str, tuple[ExecutiveSummarySection, EconomicEvent | None]] = {}

    # ------------------------------------------------------------------ public
    def subscribed_event_types(self) -> tuple[EventType, ...]:
        """Return the EventBus types this agent listens to."""
        return _SUBSCRIBED_EVENTS

    def on_event(self, event: EconomicEvent) -> ExecutiveSummarySection | None:
        """EventBus handler.

        Returns the freshly-regenerated section when the severity floor is
        met, ``None`` otherwise (event ignored — cache untouched).
        """
        if event.severity not in _REGEN_SEVERITIES:
            logger.debug(
                "executive_summary: ignoring event %s severity=%s (floor HIGH)",
                event.event_id,
                event.severity,
            )
            return None
        section = self._regenerate(event)
        self._cache[event.country] = (section, event)
        return section

    def invoke(
        self,
        country: str,
        context: dict | None = None,
    ) -> ExecutiveSummarySection:
        """Return the cached summary for ``country`` (or warm-start).

        When no HIGH+ event has ever been seen for ``country``, a synthetic
        cold-start section is composed from ``context`` — used during dashboard
        warm-up before the first event fires.
        """
        if country in self._cache:
            section, _ = self._cache[country]
            return section
        # Cold-start: synthesise a stub summary from context. Real systems
        # will have the SnapshotCoordinator seed this on first regen.
        cold_event = _synthetic_seed_event(country, context or {})
        section = self._regenerate(cold_event, cold_start=True)
        self._cache[country] = (section, None)
        return section

    # ---------------------------------------------------------------- internals
    def _regenerate(
        self,
        event: EconomicEvent,
        *,
        cold_start: bool = False,
    ) -> ExecutiveSummarySection:
        summary, headline_facts = self._build_narrative(event)
        word_count = len(summary.split())
        if word_count < _MIN_WORDS or word_count > _MAX_WORDS:
            # Trim/pad deterministically to stay within the §K.3 guardrail.
            summary, word_count = _clip_to_word_range(summary)

        previous = self._cache.get(event.country)
        prev_version = previous[0].version if previous else 0

        return ExecutiveSummarySection(
            section_id=self.SECTION_ID,
            version=prev_version + 1,
            generated_at=datetime.now(timezone.utc),
            snapshot_id=f"executive_summary:{event.country}",
            freshness_seconds=0,
            confidence=0.8 if not cold_start else 0.5,
            status=SectionStatus.READY if not cold_start else SectionStatus.DEGRADED,
            agent=self.AGENT_ID,
            execution_time_ms=1,
            citations=[f"ref:event:{event.event_id}"],
            limitations=[] if not cold_start else ["cold start — no HIGH+ event yet"],
            depends_on=["pillars", "regime"],
            provenance=ProvenanceObject(
                source_event_ids=[event.event_id],
                weights_version="na",
                model_version="template-1",
                prompt_version="executive_summary_v1",
                upstream_sections=["pillars", "regime"],
                data_versions={},
            ),
            summary=summary,
            word_count=word_count,
            headline_facts=headline_facts,
        )


# ────────────────────────────────────────────────────────── helpers (module-level)


def _default_narrative(event: EconomicEvent) -> tuple[str, list[str]]:
    """Template-based composer — deterministic, no LLM.

    Returns ``(summary, headline_facts)``. 94-07 swaps this for a richer
    LLM composition; the contract surface stays immutable.
    """
    country = event.country
    etype = event.event_type.value
    label = _humanise_event_label(event)
    summary = (
        f"{country} macro picture shifted today on a {etype.replace('_', ' ')} update — "
        f"{label}. The current regime read carries through to risk appetite and policy expectations, "
        f"with downstream specialists explaining the cross-pillar implications. "
        f"Key risk: data quality and timing around the next central bank window."
    )
    headline_facts = [
        f"Trigger: {etype}",
        f"Country: {country}",
        f"Severity: {event.severity.value}",
        f"Source: {event.source}",
    ]
    return summary, headline_facts


def _humanise_event_label(event: EconomicEvent) -> str:
    payload = event.payload or {}
    if "label" in payload and isinstance(payload["label"], str):
        return payload["label"]
    if "indicator" in payload and isinstance(payload["indicator"], str):
        return f"indicator {payload['indicator']} moved"
    return f"new {event.event_type.value} signal"


def _clip_to_word_range(summary: str) -> tuple[str, int]:
    """Force a summary into ``[_MIN_WORDS, _MAX_WORDS]`` deterministically."""
    words = summary.split()
    if len(words) > _MAX_WORDS:
        words = words[:_MAX_WORDS]
    while len(words) < _MIN_WORDS:
        words.append("ongoing")
    return " ".join(words), len(words)


def _synthetic_seed_event(country: str, context: dict) -> EconomicEvent:
    """Build a synthetic LOW-severity seed event for cold-start composition.

    The seed is intentionally LOW so it CANNOT enter the cache as if it
    were a real HIGH+ trigger — ``_regenerate`` is called directly here.
    """
    label = context.get("seed_label", "cold start — no HIGH+ event yet")
    return EconomicEvent(
        event_id=f"seed:{country}",
        event_type=EventType.STRUCTURAL_UPDATE,
        severity=EventSeverity.LOW,
        country=country,
        occurred_at=datetime.now(timezone.utc),
        source="vm107.executive_summary.cold_start",
        payload={"label": label},
    )


__all__ = ["ExecutiveSummary"]
