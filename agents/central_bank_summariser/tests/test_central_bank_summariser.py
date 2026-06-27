"""Phase 94-06 — CentralBankSummariser tests.

Locks per §K.1:
* Triggers ONLY on EventType.CENTRAL_BANK.
* Any other event family → no-op (returns None, cache untouched).
"""

from __future__ import annotations

from datetime import datetime, timezone

from agents.central_bank_summariser import CentralBankSummariser
from contracts.economic_intelligence.central_bank import CentralBankSection, CentralBankStance
from contracts.economic_intelligence.events import EconomicEvent, EventSeverity, EventType


def _cb_event(*, stance="HAWKISH", policy_rate=5.25, country="US") -> EconomicEvent:
    return EconomicEvent(
        event_id="cb-1",
        event_type=EventType.CENTRAL_BANK,
        severity=EventSeverity.HIGH,
        country=country,
        occurred_at=datetime.now(timezone.utc),
        source="vm101.central_bank",
        payload={
            "bank": "FED",
            "stance": stance,
            "policy_rate": policy_rate,
            "balance_sheet_usd_bn": 7100.0,
            "statement_title": "FOMC Decision",
            "statement_summary": "Fed held rates and signalled higher-for-longer",
        },
    )


def _other_event(etype=EventType.MACRO_RELEASE) -> EconomicEvent:
    return EconomicEvent(
        event_id="other-1",
        event_type=etype,
        severity=EventSeverity.HIGH,
        country="US",
        occurred_at=datetime.now(timezone.utc),
        source="vm101.test",
        payload={"label": "macro release"},
    )


def test_fires_only_on_central_bank_events():
    """Per §K.1 — agent.on_event() with non-CENTRAL_BANK event is a no-op."""
    agent = CentralBankSummariser()
    for etype in [EventType.MACRO_RELEASE, EventType.REGIME_CHANGE,
                  EventType.FORECAST_UPDATE, EventType.RESEARCH,
                  EventType.DISCOVERY, EventType.ALERT,
                  EventType.STRUCTURAL_UPDATE]:
        assert agent.on_event(_other_event(etype=etype)) is None, (
            f"central_bank_summariser must ignore {etype} per §K.1"
        )


def test_subscription_matrix_is_central_bank_only():
    agent = CentralBankSummariser()
    assert agent.subscribed_event_types() == (EventType.CENTRAL_BANK,)


def test_central_bank_event_emits_section():
    agent = CentralBankSummariser()
    section = agent.on_event(_cb_event())
    assert isinstance(section, CentralBankSection)
    assert section.bank == "FED"
    assert section.stance is CentralBankStance.HAWKISH
    assert section.policy_rate == 5.25
    assert section.balance_sheet_usd_bn == 7100.0
    assert section.latest_statement is not None
    assert "Fed held rates" in section.latest_statement.summary


def test_country_to_bank_fallback_used_when_payload_omits_bank():
    agent = CentralBankSummariser()
    event = EconomicEvent(
        event_id="cb-2",
        event_type=EventType.CENTRAL_BANK,
        severity=EventSeverity.HIGH,
        country="EU",
        occurred_at=datetime.now(timezone.utc),
        source="vm101.test",
        payload={"stance": "DOVISH", "policy_rate": 4.0},
    )
    section = agent.on_event(event)
    assert section is not None
    assert section.bank == "ECB"
    assert section.stance is CentralBankStance.DOVISH


def test_invoke_returns_none_before_any_event():
    agent = CentralBankSummariser()
    assert agent.invoke("US") is None


def test_invoke_returns_cached_after_event():
    agent = CentralBankSummariser()
    section = agent.on_event(_cb_event())
    cached = agent.invoke("US")
    assert cached is section


def test_version_increments_on_subsequent_events():
    agent = CentralBankSummariser()
    s1 = agent.on_event(_cb_event())
    s2 = agent.on_event(_cb_event())
    assert s2.version == s1.version + 1
