"""Phase 94-06 — Timeline agent (APPEND-ONLY event log per §K.4).

Per §K.4 lock: the timeline is never regenerated wholesale. Each incoming
EconomicEvent is appended to the per-country log; subsequent events extend
the log rather than replacing it.

Window filtering ("last 24h", "last 7d") lives in the Wave 4 serializer —
this agent stores everything; the serializer slices for the dashboard.
A convenience helper :meth:`filter_window` is exposed so the Wave 4
serializer (and tests) can reuse the same logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.events import EconomicEvent
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.timeline import TimelineEntry, TimelineSection

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────── window parsing


def _parse_window(window: str) -> timedelta:
    """Parse a window string like "24h", "7d", "30m"."""
    window = window.strip().lower()
    if window.endswith("h"):
        return timedelta(hours=int(window[:-1]))
    if window.endswith("d"):
        return timedelta(days=int(window[:-1]))
    if window.endswith("m"):
        return timedelta(minutes=int(window[:-1]))
    raise ValueError(f"unrecognised window format: {window!r} (expected '24h', '7d', '30m')")


class Timeline:
    """Append-only timeline of EconomicEvent fires."""

    AGENT_ID = "vm107.timeline"
    SECTION_ID = "timeline"

    def __init__(self) -> None:
        # country -> [TimelineEntry] in arrival order.
        self._log: dict[str, list[TimelineEntry]] = {}
        self._version: dict[str, int] = {}

    # ------------------------------------------------------------------ public
    def on_event(self, event: EconomicEvent) -> TimelineSection:
        """Append the event and return the (full) updated TimelineSection."""
        entry = TimelineEntry(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            label=_humanise_label(event),
            severity=event.severity,
            deep_link=f"/markets/macro/event/{event.event_id}",
        )
        self._log.setdefault(event.country, []).append(entry)
        self._version[event.country] = self._version.get(event.country, 0) + 1
        return self._compose_section(event.country, snapshot_id=f"timeline:{event.country}")

    def invoke(
        self,
        country: str,
        window: str | None = None,
        snapshot_id: str | None = None,
    ) -> TimelineSection:
        """Return the current TimelineSection for ``country`` (optionally
        window-filtered for serializer compatibility)."""
        return self._compose_section(
            country,
            window=window,
            snapshot_id=snapshot_id or f"timeline:{country}",
        )

    def filter_window(
        self,
        entries: list[TimelineEntry],
        window: str,
        now: datetime | None = None,
    ) -> list[TimelineEntry]:
        """Return entries within ``window`` of ``now`` (default: utcnow)."""
        delta = _parse_window(window)
        ref = now or datetime.now(timezone.utc)
        return [e for e in entries if (ref - _aware(e.occurred_at)) <= delta]

    # ---------------------------------------------------------------- internals
    def _compose_section(
        self,
        country: str,
        *,
        window: str | None = None,
        snapshot_id: str,
    ) -> TimelineSection:
        entries = list(self._log.get(country, []))
        if window:
            entries = self.filter_window(entries, window)
        version = self._version.get(country, 1)
        status = SectionStatus.READY if entries else SectionStatus.UNAVAILABLE
        return TimelineSection(
            section_id=self.SECTION_ID,
            version=version,
            generated_at=datetime.now(timezone.utc),
            snapshot_id=snapshot_id,
            freshness_seconds=0,
            confidence=1.0,  # Append-only log — full confidence in the data.
            status=status,
            agent=self.AGENT_ID,
            execution_time_ms=1,
            citations=[f"ref:event:{e.event_id}" for e in entries],
            limitations=[],
            depends_on=["event_bus"],
            provenance=ProvenanceObject(
                source_event_ids=[e.event_id for e in entries],
                weights_version="na",
                model_version="na",
                prompt_version="na",
                upstream_sections=[],
                data_versions={},
            ),
            entries=entries,
        )


# ─────────────────────────────────────────────────────────── helpers


def _humanise_label(event: EconomicEvent) -> str:
    payload = event.payload or {}
    if isinstance(payload.get("label"), str):
        return payload["label"]
    return f"{event.event_type.value} from {event.source}"


def _aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


__all__ = ["Timeline"]
