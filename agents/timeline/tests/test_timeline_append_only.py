"""Phase 94-06 — Timeline append-only behaviour (§K.4).

Locks:
* Events are appended in arrival order; never replaced wholesale.
* invoke(window="24h") filters by recency without mutating the log.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agents.timeline import Timeline
from contracts.economic_intelligence.events import EconomicEvent, EventSeverity, EventType


def _event(event_id: str, *, country: str = "US",
           occurred_at: datetime | None = None,
           etype: EventType = EventType.MACRO_RELEASE) -> EconomicEvent:
    return EconomicEvent(
        event_id=event_id,
        event_type=etype,
        severity=EventSeverity.MEDIUM,
        country=country,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        source="vm101.test",
        payload={"label": f"event {event_id}"},
    )


def test_event_appended_not_replaced():
    timeline = Timeline()
    section1 = timeline.on_event(_event("e1"))
    section2 = timeline.on_event(_event("e2"))
    section3 = timeline.on_event(_event("e3"))

    assert [e.event_id for e in section3.entries] == ["e1", "e2", "e3"]
    assert len(section3.entries) == 3

    # Firing a 4th event preserves prior entries.
    section4 = timeline.on_event(_event("e4"))
    assert [e.event_id for e in section4.entries] == ["e1", "e2", "e3", "e4"]


def test_window_filter_applied():
    timeline = Timeline()
    now = datetime.now(timezone.utc)
    # 3 within 24h, 2 outside.
    timeline.on_event(_event("recent1", occurred_at=now - timedelta(hours=1)))
    timeline.on_event(_event("recent2", occurred_at=now - timedelta(hours=12)))
    timeline.on_event(_event("recent3", occurred_at=now - timedelta(hours=23)))
    timeline.on_event(_event("old1", occurred_at=now - timedelta(hours=48)))
    timeline.on_event(_event("old2", occurred_at=now - timedelta(days=7)))

    windowed = timeline.invoke("US", window="24h")
    ids = {e.event_id for e in windowed.entries}
    assert ids == {"recent1", "recent2", "recent3"}

    # The underlying log is untouched — full invoke still returns all 5.
    full = timeline.invoke("US")
    assert len(full.entries) == 5


def test_multi_country_isolation():
    timeline = Timeline()
    timeline.on_event(_event("us1", country="US"))
    timeline.on_event(_event("eu1", country="EU"))
    timeline.on_event(_event("us2", country="US"))

    us = timeline.invoke("US")
    eu = timeline.invoke("EU")
    assert [e.event_id for e in us.entries] == ["us1", "us2"]
    assert [e.event_id for e in eu.entries] == ["eu1"]


def test_version_increments_monotonically():
    timeline = Timeline()
    v1 = timeline.on_event(_event("e1"))
    v2 = timeline.on_event(_event("e2"))
    v3 = timeline.on_event(_event("e3"))
    assert (v1.version, v2.version, v3.version) == (1, 2, 3)


def test_empty_invoke_returns_unavailable():
    timeline = Timeline()
    section = timeline.invoke("US")
    assert section.status.value == "UNAVAILABLE"
    assert section.entries == []
