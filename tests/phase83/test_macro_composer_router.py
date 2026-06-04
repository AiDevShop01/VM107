"""REQ-83-F1 — IntelligenceFeedMacroComposer must use LLM router, not anthropic SDK directly.

Wave 4 Plan 09 will GREEN these tests by shipping:
  VM107/emitters/intelligence_feed_macro_composer.py (new location, LLM-router wired)

Pitfall 6 (from CONTEXT.md): Using anthropic.Anthropic() directly bypasses the Phase 43
ModelRouter, which means cost tracking, budget gates, and Agent Hands routing all fail.
The composer must call router.decide(ctx) then use the returned model name.
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.phase83
def test_router_invoked_not_anthropic_sdk():
    """IntelligenceFeedMacroComposer calls LLM router, never anthropic.Anthropic() directly.

    REQ-83-F1, Pitfall 6: Mock both the router and anthropic SDK. Assert that:
    1. ModelRouter.decide() was called at least once
    2. anthropic.Anthropic() was NEVER instantiated during the call

    This test is the regression guard against Pitfall 6 recurrence.
    """
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_composer_uses_agent_hands_profile():
    """IntelligenceFeedMacroComposer passes path='utility' (Agent Hands) to RouterContext.

    REQ-83-F1: MACRO composer is a utility call (Agent Hands profile), not a chat call.
    RouterContext.path must be 'utility' so cost-first routing applies.
    """
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_composer_goal_id_is_macro_goal():
    """RouterContext.goal_id is set to 'vm107.macro' for budget tracking.

    REQ-83-F1: All composer LLM calls must be attributed to the 'vm107.macro'
    goal so Phase 43 budget tracking aggregates MACRO costs correctly.
    """
    from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")
