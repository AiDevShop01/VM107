"""Phase 94-06 — Executive Summary event subscription + cache (Wave-0 RED → GREEN).

Locks per §K.3 + REQ-94-5:

* HIGH or CRITICAL events trigger regeneration.
* LOW / MEDIUM events are ignored — cache untouched.
* Cached summary returned when no new HIGH+ event has arrived since last regen.
* Summary word count guardrail: 30..60 words inclusive.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.executive_summary import ExecutiveSummary
from contracts.economic_intelligence.events import EconomicEvent, EventSeverity, EventType
from contracts.economic_intelligence.executive_summary import ExecutiveSummarySection


def _event(*, severity: EventSeverity, event_type: EventType = EventType.CENTRAL_BANK,
           event_id: str = "evt-1", country: str = "US",
           label: str = "Fed delivered a hawkish hold") -> EconomicEvent:
    return EconomicEvent(
        event_id=event_id,
        event_type=event_type,
        severity=severity,
        country=country,
        occurred_at=datetime.now(timezone.utc),
        source="vm101.test",
        payload={"label": label},
    )


def test_executive_summary_regens_on_high_event():
    agent = ExecutiveSummary()
    section = agent.on_event(_event(severity=EventSeverity.HIGH))
    assert isinstance(section, ExecutiveSummarySection)
    assert section.agent == "vm107.executive_summary"


def test_executive_summary_regens_on_critical_event():
    agent = ExecutiveSummary()
    section = agent.on_event(_event(severity=EventSeverity.CRITICAL, event_id="evt-c"))
    assert isinstance(section, ExecutiveSummarySection)


@pytest.mark.parametrize("low_sev", [EventSeverity.LOW, EventSeverity.MEDIUM])
def test_low_or_medium_severity_event_does_not_trigger_regen(low_sev):
    agent = ExecutiveSummary()
    out = agent.on_event(_event(severity=low_sev, event_type=EventType.RESEARCH,
                                event_id="evt-low"))
    assert out is None, f"severity={low_sev} must NOT regen per §K.3"


def test_cached_summary_returned_when_no_new_high_event():
    """invoke() returns the cached section between regenerations.

    Counts the number of regenerations (proxy for LLM calls in the future)
    via a wrapper around the deterministic narrative builder.
    """
    calls: list[str] = []

    def counting_builder(event: EconomicEvent):
        calls.append(event.event_id)
        return (
            "Macro picture shifted today with a notable policy update from the central bank "
            "carrying through to risk appetite and inflation expectations. "
            "Specialists will explain cross-pillar implications in the next section.",
            ["Trigger: central_bank", "Country: US"],
        )

    agent = ExecutiveSummary(narrative_builder=counting_builder)
    # First HIGH event triggers a regen.
    first = agent.on_event(_event(severity=EventSeverity.HIGH, event_id="evt-1"))
    assert first is not None
    assert len(calls) == 1

    # invoke() returns the cached section — must NOT call the builder again.
    cached = agent.invoke("US")
    assert cached is first
    assert len(calls) == 1, "invoke() called the builder again — cache violation"

    # A LOW event arrives — still no regen.
    assert agent.on_event(_event(severity=EventSeverity.LOW, event_id="evt-low")) is None
    assert len(calls) == 1

    # invoke() again — still cached.
    cached2 = agent.invoke("US")
    assert cached2 is first
    assert len(calls) == 1


def test_summary_word_count_30_to_60():
    agent = ExecutiveSummary()
    section = agent.on_event(_event(severity=EventSeverity.HIGH, event_id="evt-wc"))
    assert section is not None
    wc = section.word_count
    assert 30 <= wc <= 60, f"word count {wc} outside [30, 60] guardrail (§K.3)"
    assert section.word_count == len(section.summary.split())


def test_subscribed_event_types_cover_high_severity_families():
    agent = ExecutiveSummary()
    subscribed = set(agent.subscribed_event_types())
    # §K.3 — exec summary listens to all event families that can flip the
    # macro headline. Discovery / research / alerts feed other sections.
    assert {
        EventType.MACRO_RELEASE,
        EventType.CENTRAL_BANK,
        EventType.REGIME_CHANGE,
        EventType.FORECAST_UPDATE,
    }.issubset(subscribed)


def test_cold_start_invoke_returns_degraded_section():
    """invoke() without a prior HIGH+ event still returns a section.

    Status must be DEGRADED with an explicit cold-start limitation —
    never UNAVAILABLE or ERROR (the SnapshotCoordinator surfaces empty
    states with its own envelope).
    """
    agent = ExecutiveSummary()
    section = agent.invoke("US", context={"seed_label": "warming up"})
    assert section.status.value == "DEGRADED"
    assert any("cold start" in lim.lower() for lim in section.limitations)
    assert 30 <= section.word_count <= 60
