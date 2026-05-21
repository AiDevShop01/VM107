"""BUG-23 / Phase 62.1: unit tests for model-tier routing via get_chat_model().

The _model_config plugin's get_chat_model extension now routes to the utility
model when the agent's profile has model_tier='utility', and to the chat model
otherwise (the existing behavior for all brain agents).

Tests cover:
  1. Agent with model_tier='chat' → get_chat_model() returns chat model
  2. Agent with model_tier='utility' → get_chat_model() returns utility model
  3. Agent with no model_tier (None) → defaults to chat model (brain-preservation)
  4. SubAgent load error → gracefully defaults to chat model
  5. Tier result cached on agent.data — load_agent_data called only once
  6. agent=None → no-op
  7. BRAIN PRESERVATION: top-level brain profiles (real YAML) → chat model, NOT utility
  8. Reader sub-profiles (real YAML) → utility model

Patch paths: the extension imports build_chat_model and build_utility_model by name
into its own module namespace, so patches must target the extension module namespace.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

# Patch paths — target the extension's own namespace where the names were imported
_EXT_MOD = (
    "plugins._model_config.extensions.python._functions"
    ".agent.Agent.get_chat_model.start._10_model_config"
)
_BUILD_CHAT = f"{_EXT_MOD}.build_chat_model"
_BUILD_UTIL = f"{_EXT_MOD}.build_utility_model"
# load_agent_data is called via `from helpers import subagents; subagents.load_agent_data()`
# inside a lazy import, so patch the source location
_LOAD_AGENT = "helpers.subagents.load_agent_data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extension(profile: str, agent_data: dict | None = None):
    """Build a ChatModelProvider extension with a fake agent at the given profile."""
    from plugins._model_config.extensions.python._functions.agent.Agent.get_chat_model.start._10_model_config import (
        ChatModelProvider,
    )
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.profile = profile
    agent.data = agent_data if agent_data is not None else {}
    return ChatModelProvider(agent=agent), agent


def _fake_sub(model_tier: str | None) -> MagicMock:
    """Return a mock SubAgent with a given model_tier."""
    sub = MagicMock()
    sub.model_tier = model_tier
    return sub


# ---------------------------------------------------------------------------
# Tests: routing logic
# ---------------------------------------------------------------------------


class TestModelTierRouting:
    """Tests for the extension's _resolve_model_tier → route decision."""

    def test_chat_tier_returns_chat_model(self):
        """profile with model_tier='chat' → extension calls build_chat_model."""
        ext, agent = _make_extension("some_agent._reader")
        data = {}

        with patch(_LOAD_AGENT, return_value=_fake_sub("chat")), \
             patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "CHAT_MODEL"
        mock_chat.assert_called_once()
        mock_util.assert_not_called()

    def test_utility_tier_returns_utility_model(self):
        """profile with model_tier='utility' → extension calls build_utility_model."""
        ext, agent = _make_extension("trade_auditor_agent._reader")
        data = {}

        with patch(_LOAD_AGENT, return_value=_fake_sub("utility")), \
             patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "UTILITY_MODEL"
        mock_util.assert_called_once()
        mock_chat.assert_not_called()

    def test_no_model_tier_defaults_to_chat(self):
        """profile with model_tier=None (absent field) → defaults to chat model."""
        ext, agent = _make_extension("trade_auditor_agent")
        data = {}

        with patch(_LOAD_AGENT, return_value=_fake_sub(None)), \
             patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "CHAT_MODEL"
        mock_chat.assert_called_once()
        mock_util.assert_not_called()

    def test_load_agent_data_error_defaults_to_chat(self):
        """If SubAgent loading fails, gracefully fall through to chat model."""
        ext, agent = _make_extension("unknown_profile._reader")
        data = {}

        with patch(_LOAD_AGENT, side_effect=Exception("not found")), \
             patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "CHAT_MODEL"
        mock_util.assert_not_called()

    def test_tier_cached_on_agent_data(self):
        """Tier result is cached on agent.data — load_agent_data called only once."""
        ext, agent = _make_extension("cached_profile._reader")
        data = {}

        with patch(_LOAD_AGENT, return_value=_fake_sub("utility")) as mock_load, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL"):
            ext.execute(data=data)
            ext.execute(data=data)  # second call — must not re-load

        assert mock_load.call_count == 1, (
            "load_agent_data should be called only once (tier caching)"
        )

    def test_agent_none_is_noop(self):
        """agent=None → extension is a no-op (does not set data['result'])."""
        from plugins._model_config.extensions.python._functions.agent.Agent.get_chat_model.start._10_model_config import (
            ChatModelProvider,
        )
        ext = ChatModelProvider(agent=None)
        data = {}
        ext.execute(data=data)
        assert "result" not in data


# ---------------------------------------------------------------------------
# Brain-preservation tests (FAIL LOUDLY if regression introduced)
# ---------------------------------------------------------------------------


class TestBrainPreservationModelRouting:
    """BRAIN PRESERVATION: top-level brain agents must always get the chat model.

    These tests use real SubAgent data from the actual agent.yaml files.
    They FAIL LOUDLY if:
      - Someone adds model_tier to a brain's top-level agent.yaml
      - The routing logic has a bug that biases the brain to utility tier
    """

    @pytest.mark.parametrize("brain_profile", [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ])
    def test_brain_gets_chat_model_not_utility(self, brain_profile):
        """BRAIN PRESERVATION: top-level brain profile → get_chat_model() returns chat model.

        Uses real SubAgent data from disk — no mocking of load_agent_data.
        """
        ext, agent = _make_extension(brain_profile)
        data = {}

        with patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "CHAT_MODEL", (
            f"BRAIN PRESERVATION VIOLATED: {brain_profile!r} resolved to utility model. "
            "Top-level brain agents must ALWAYS use the chat model. "
            "Check that model_tier is not set in the brain's top-level agent.yaml."
        )
        mock_util.assert_not_called()

    @pytest.mark.parametrize("reader_profile", [
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ])
    def test_reader_gets_utility_model(self, reader_profile):
        """Reader sub-profiles with model_tier=utility (real YAML) → utility model."""
        ext, agent = _make_extension(reader_profile)
        data = {}

        with patch(_BUILD_CHAT, return_value="CHAT_MODEL") as mock_chat, \
             patch(_BUILD_UTIL, return_value="UTILITY_MODEL") as mock_util:
            ext.execute(data=data)

        assert data["result"] == "UTILITY_MODEL", (
            f"{reader_profile!r}: expected utility model but got chat model. "
            "Did the model_tier: utility field in agent.yaml get loaded correctly?"
        )
        mock_chat.assert_not_called()
