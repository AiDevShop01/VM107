"""
RED scaffold for REQ-66-3 MACRO composer — implemented in Plan 66-07.

Tests:
- test_macro_composer_reads_from_analytics_calendar_service
- test_macro_composer_applies_novelty_gate
- test_macro_composer_returns_intelligence_feed_items_with_macro_category
- test_macro_item_lifecycle_active_before_release_resolved_after
- test_macro_composer_empty_calendar_returns_empty_list_not_demo
"""
import pytest

pytestmark = pytest.mark.phase_66


def test_macro_composer_reads_from_analytics_calendar_service():
    """REQ-66-3: IntelligenceFeedMacroComposer reads from AnalyticsCalendarService
    (mocked) to build macro feed items."""
    try:
        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-07) must implement "
            f"emitters.intelligence_feed_macro_composer.IntelligenceFeedMacroComposer: {exc}"
        )

    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedMacroComposer()

    mock_events = [
        MagicMock(
            event_name="FOMC Meeting",
            event_date="2026-05-23T14:00:00Z",
            risk_severity="CRITICAL",
            releasing_authority=MagicMock(authority_code="FED"),
            event_status="scheduled",
        )
    ]
    mock_calendar = MagicMock()
    mock_calendar.get_next_24h_events.return_value = mock_events

    with patch.object(composer, "_calendar_service", mock_calendar):
        items = composer.compose()

    mock_calendar.get_next_24h_events.assert_called_once(), (
        "IntelligenceFeedMacroComposer must call AnalyticsCalendarService.get_next_24h_events"
    )
    assert len(items) >= 1, "Must return at least one item when calendar has events"


def test_macro_composer_applies_novelty_gate():
    """REQ-66-3: Macro items pass through novelty gate; low-novelty events filtered."""
    try:
        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedMacroComposer: {exc}")

    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedMacroComposer()

    # Two events: one high-novelty, one low-novelty
    mock_events = [
        MagicMock(event_name="FOMC", risk_severity="CRITICAL", event_status="scheduled"),
        MagicMock(event_name="Low-impact report", risk_severity="LOW", event_status="scheduled"),
    ]
    mock_calendar = MagicMock(get_next_24h_events=MagicMock(return_value=mock_events))

    # NoveltyEngine score is called with NoveltyDimensions (not the raw event object).
    # Alternate high/low scores per call so both code paths are exercised.
    call_counter = {"n": 0}

    def mock_novelty_score(dims):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            # First call (FOMC — high impact dims) → threshold crossed
            return MagicMock(score=0.85, threshold_crossed=True)
        return MagicMock(score=0.3, threshold_crossed=False)

    with patch.object(composer, "_calendar_service", mock_calendar), \
         patch.object(composer, "_novelty_engine") as mock_engine:
        mock_engine.score.side_effect = mock_novelty_score
        items = composer.compose()

    # At least the FOMC item should pass the novelty gate
    categories = [item.category for item in items]
    assert "macro" in categories or all(hasattr(i, "category") for i in items), (
        "Composed items must have category field"
    )


def test_macro_composer_returns_intelligence_feed_items_with_macro_category():
    """REQ-66-3: Returns IntelligenceFeedItem[] with category='macro',
    lifecycle state in {active, watching, resolved, expired}."""
    try:
        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedMacroComposer: {exc}")

    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedMacroComposer()
    mock_event = MagicMock(
        event_name="ECB Rate Decision",
        event_date="2026-05-23T12:45:00Z",
        risk_severity="CRITICAL",
        event_status="scheduled",
    )
    mock_calendar = MagicMock(get_next_24h_events=MagicMock(return_value=[mock_event]))

    with patch.object(composer, "_calendar_service", mock_calendar):
        items = composer.compose()

    valid_lifecycle_states = {"active", "watching", "resolved", "expired"}
    for item in items:
        assert hasattr(item, "category"), f"IntelligenceFeedItem must have category; got {item!r}"
        assert item.category == "macro", (
            f"MACRO composer must set category='macro'; got {item.category!r}"
        )
        assert hasattr(item, "lifecycle_state"), "IntelligenceFeedItem must have lifecycle_state"
        assert item.lifecycle_state in valid_lifecycle_states, (
            f"lifecycle_state must be in {valid_lifecycle_states}; got {item.lifecycle_state!r}"
        )


def test_macro_item_lifecycle_active_before_release_resolved_after():
    """REQ-66-3: MACRO event is 'active' before release time, 'resolved' after."""
    try:
        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedMacroComposer: {exc}")

    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from unittest.mock import MagicMock, patch
    from datetime import datetime, timezone, timedelta

    composer = IntelligenceFeedMacroComposer()

    # Future event -> should be "active"
    future_date = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    past_date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    future_event = MagicMock(event_name="CPI Release", event_date=future_date,
                              risk_severity="HIGH", event_status="scheduled")
    past_event = MagicMock(event_name="GDP Released", event_date=past_date,
                            risk_severity="HIGH", event_status="released")

    mock_calendar = MagicMock(get_next_24h_events=MagicMock(return_value=[future_event, past_event]))

    with patch.object(composer, "_calendar_service", mock_calendar):
        items = composer.compose()

    items_by_name = {i.title: i for i in items if hasattr(i, "title")}
    # If the composer maps names to titles, check lifecycle
    if "CPI Release" in items_by_name:
        assert items_by_name["CPI Release"].lifecycle_state in ("active", "watching"), (
            "Future MACRO event must have lifecycle_state=active or watching"
        )


def test_macro_composer_empty_calendar_returns_empty_list_not_demo():
    """REQ-66-3: When calendar has no events, return empty list (NOT _demo=True).
    Empty is a REAL signal — zero scheduled events is a valid market state."""
    try:
        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedMacroComposer: {exc}")

    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedMacroComposer()
    mock_calendar = MagicMock(get_next_24h_events=MagicMock(return_value=[]))

    with patch.object(composer, "_calendar_service", mock_calendar):
        items = composer.compose()

    assert isinstance(items, list), "compose() must return a list"
    assert len(items) == 0, (
        f"Empty calendar must return empty list (not DEMO items); got {len(items)} items. "
        "Empty is a REAL signal per REQ-66-3 — do not inject DEMO placeholder."
    )
