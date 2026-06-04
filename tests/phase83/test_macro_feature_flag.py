"""REQ-83-H2 — MACRO_FEED_ENABLED feature flag controls emitter behavior.

Wave 5 Plan 10 will GREEN these tests.

Feature flag semantics:
  MACRO_FEED_ENABLED=true  → normal emitter operation (real calendar + LLM)
  MACRO_FEED_ENABLED=false → immediate DEMO mode (no calendar API, no LLM call)

This flag is an emergency shutoff that can disable the MACRO feed without
redeploying the service (read from env at cycle start, not just at startup).
"""
import pytest


@pytest.mark.phase83
def test_flag_off_returns_demo():
    """MACRO_FEED_ENABLED=false → emitter cycle returns DEMO placeholder immediately.

    REQ-83-H2: When the feature flag is off, the emitter must NOT call the calendar
    API or LLM router. It must return the Phase 65-10 DEMO placeholder directly.
    No network calls should occur.
    """
    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter  # noqa: F401

    pytest.fail("RED skeleton — Wave 5 Plan 10 will GREEN this")


@pytest.mark.phase83
def test_flag_on_calls_calendar_api():
    """MACRO_FEED_ENABLED=true → emitter cycle calls the calendar API.

    REQ-83-H2: When the feature flag is on, the emitter must call
    MacroCalendarClient.get_upcoming_events() as the first step of the cycle.
    """
    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter  # noqa: F401

    pytest.fail("RED skeleton — Wave 5 Plan 10 will GREEN this")


@pytest.mark.phase83
def test_flag_is_checked_per_cycle_not_just_startup():
    """The MACRO_FEED_ENABLED flag is read from env on each cycle (not cached at startup).

    REQ-83-H2: Operators must be able to flip the flag via environment variable
    without restarting the container. The emitter reads os.getenv('MACRO_FEED_ENABLED')
    at the TOP of each cycle, not once in __init__.
    """
    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter  # noqa: F401

    pytest.fail("RED skeleton — Wave 5 Plan 10 will GREEN this")
