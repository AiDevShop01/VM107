"""Phase 86 Plan 10 UAT — backfill direct LLM dispatch path.

The Agent Zero path (`_dispatch_agent_sync` → `/api/api_message`) corrupted
itself after 2-3 calls during Phase 86-10 UAT:
  - AAA + ANFCI wrote cleanly
  - BAA onwards: `ValueError: Tool request must have a tool_name field` from
    A0's tool-call validation rejecting the agent's editorial JSON response.

The fix bypasses A0 entirely for the describer profile via
`_dispatch_describer_direct`, which calls litellm.completion() with no
intermediate agent runtime. Stateless per call.

Tests here verify:
1. The default path calls litellm (not A0).
2. The BACKFILL_USE_AGENT_ZERO=1 env var routes back to the legacy A0 path.
3. Direct dispatch fails fast when API_KEY_<provider> is unset.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_litellm_response(content: str):
    """Build a litellm-shaped response object."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage.prompt_tokens = 200
    resp.usage.completion_tokens = 120
    resp.usage.total_tokens = 320
    resp.model = "deepseek-v4-flash"
    return resp


def test_direct_dispatch_calls_litellm_not_agent_zero(monkeypatch):
    """Default path (BACKFILL_USE_AGENT_ZERO unset) → litellm.completion(), not A0."""
    monkeypatch.setenv("API_KEY_DEEPSEEK", "test-key-stub")
    monkeypatch.delenv("BACKFILL_USE_AGENT_ZERO", raising=False)

    indicators = [
        {
            "indicator_id": "TEST_X",
            "indicator_name": "Test Indicator X",
            "formula": "",
            "components": [],
            "importance": "MED",
            "source_agency_code": "FRED",
            "frequency": "monthly",
            "is_manual_override": False,
        }
    ]

    json_payload = (
        '{"what_is_it": "An indicator.", '
        '"why_important": "It matters.", '
        '"why_traders_care": "Traders watch it."}'
    )

    mock_completion = MagicMock(return_value=_mock_litellm_response(json_payload))
    mock_a0 = MagicMock(return_value=("should_not_be_called", {}))
    mock_upsert = MagicMock()

    with (
        patch(
            "backfill.backfill_indicator_descriptions.fetch_indicators_for_backfill",
            return_value=indicators,
        ),
        patch("litellm.completion", mock_completion),
        patch(
            "backfill.backfill_indicator_descriptions._dispatch_agent_sync",
            mock_a0,
        ),
        patch(
            "persistence.economic_indicator_description.upsert_description",
            mock_upsert,
        ),
    ):
        from backfill import backfill_indicator_descriptions

        backfill_indicator_descriptions.main(indicator="TEST_X")

    assert mock_completion.call_count == 1, "litellm.completion must be called exactly once"
    assert mock_a0.call_count == 0, "Agent Zero path must NOT be called when toggle is off"
    assert mock_upsert.call_count == 1, "upsert_description must be called exactly once"


def test_use_agent_zero_toggle_routes_through_a0(monkeypatch):
    """BACKFILL_USE_AGENT_ZERO=1 → restores legacy A0 dispatch path."""
    monkeypatch.setenv("BACKFILL_USE_AGENT_ZERO", "1")

    indicators = [
        {
            "indicator_id": "TEST_Y",
            "indicator_name": "Test Y",
            "formula": "",
            "components": [],
            "importance": "MED",
            "source_agency_code": "FRED",
            "frequency": "monthly",
            "is_manual_override": False,
        }
    ]

    json_payload = (
        '{"what_is_it": "y", "why_important": "y", "why_traders_care": "y"}'
    )

    mock_a0 = MagicMock(return_value=(json_payload, {"model_used": "a0-route"}))
    mock_litellm = MagicMock()
    mock_upsert = MagicMock()

    with (
        patch(
            "backfill.backfill_indicator_descriptions.fetch_indicators_for_backfill",
            return_value=indicators,
        ),
        patch(
            "backfill.backfill_indicator_descriptions._dispatch_agent_sync",
            mock_a0,
        ),
        patch("litellm.completion", mock_litellm),
        patch(
            "persistence.economic_indicator_description.upsert_description",
            mock_upsert,
        ),
    ):
        from backfill import backfill_indicator_descriptions

        backfill_indicator_descriptions.main(indicator="TEST_Y")

    assert mock_a0.call_count == 1, "A0 path must be called when BACKFILL_USE_AGENT_ZERO=1"
    assert mock_litellm.call_count == 0, "litellm must NOT be called when A0 toggle on"
    assert mock_upsert.call_count == 1


def test_direct_dispatch_fails_fast_when_api_key_missing(monkeypatch):
    """Direct dispatch must raise RuntimeError when API_KEY_<provider> is unset."""
    monkeypatch.delenv("API_KEY_DEEPSEEK", raising=False)
    monkeypatch.delenv("BACKFILL_USE_AGENT_ZERO", raising=False)
    monkeypatch.setenv("CHAT_MODEL", "deepseek/deepseek-chat")

    from backfill.backfill_indicator_descriptions import _dispatch_describer_direct

    indicator = {
        "indicator_id": "TEST_Z",
        "indicator_name": "Test Z",
        "formula": "",
        "components": [],
        "importance": "MED",
        "source_agency_code": "FRED",
        "frequency": "monthly",
        "is_manual_override": False,
    }

    with pytest.raises(RuntimeError, match=r"API_KEY_DEEPSEEK.*REQUIRED"):
        _dispatch_describer_direct(indicator)
