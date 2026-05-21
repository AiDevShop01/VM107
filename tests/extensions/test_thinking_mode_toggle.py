"""BUG-23 / Phase 62.1: unit tests for the ThinkingModeToggle extension.

The extension translates the thinking_mode capability flag from agent.yaml into
provider-specific extra_body kwargs via a unified_call monkey-patch (same pattern
as _router_apply.py).

Test coverage:
  1. DeepSeek model + thinking_mode=False → extra_body.thinking.type == "disabled"
  2. DeepSeek model + thinking_mode=True → extra_body.thinking.type == "enabled"
  3. Non-DeepSeek model (anthropic/...) + thinking_mode=False → no injection, no crash
  4. No thinking_mode set on agent (None) → no injection (brain default preserved)
  5. Idempotent: if extra_body.thinking is already set upstream, NOT overwritten
  6. call_data=None → no exception
  7. agent=None → no exception
  8. model identifier absent from call_data → no injection, no crash
  9. unified_call wrapper is installed on the model instance, not globally
 10. Brain profiles (real YAMLs) → no injection (thinking_mode not set)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

from extensions.python.chat_model_call_before._thinking_mode_toggle import (  # noqa: E402
    ThinkingModeToggle,
    _resolve_thinking_mode,
    _is_deepseek_model,
    _wrap_unified_call_with_thinking,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(profile: str, thinking_mode: bool | None = None) -> MagicMock:
    """Build a fake Agent with a given profile and pre-cached thinking_mode."""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.profile = profile
    # Pre-seed the cache so we don't need subagents.load_agent_data in most tests
    if thinking_mode is not None or profile == "":
        agent.data = {"_bug23_thinking_cache": {"value": thinking_mode}}
    else:
        agent.data = {}
    return agent


def _make_model(model_name: str) -> tuple[MagicMock, list[dict]]:
    """Return a fake LiteLLMChatWrapper model and a list that records unified_call kwargs."""
    received: list[dict] = []

    async def _unified_call(**kw):
        received.append(dict(kw))
        return ("response", "reasoning")

    model = MagicMock()
    model.model_name = model_name
    model.unified_call = _unified_call
    return model, received


def _call_data_for(model) -> dict:
    return {"model": model}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _simulate_call(call_data: dict) -> dict | None:
    """Invoke call_data['model'].unified_call() and return the kwargs it received."""
    received: list[dict] = []
    original = call_data["model"].unified_call

    async def _capture(**kw):
        received.append(dict(kw))
        return await original(**kw) if asyncio.iscoroutinefunction(original) else ("", "")

    # If unified_call was monkey-patched by the extension, call the patched version
    _run(call_data["model"].unified_call())
    # For patched calls, the wrapper doesn't need to be called again
    return received[0] if received else None


# ---------------------------------------------------------------------------
# Tests: provider detection
# ---------------------------------------------------------------------------


class TestIsDeepSeekModel:
    def test_deepseek_slash_prefix(self):
        assert _is_deepseek_model("deepseek/deepseek-v4-flash") is True

    def test_deepseek_v4_prefix(self):
        assert _is_deepseek_model("deepseek-v4-flash") is True

    def test_deepseek_r_prefix(self):
        assert _is_deepseek_model("deepseek-r1") is True

    def test_anthropic_is_not_deepseek(self):
        assert _is_deepseek_model("anthropic/claude-sonnet-4") is False

    def test_openai_is_not_deepseek(self):
        assert _is_deepseek_model("openai/gpt-4o") is False

    def test_empty_is_not_deepseek(self):
        assert _is_deepseek_model("") is False


# ---------------------------------------------------------------------------
# Tests: extra_body injection via unified_call wrapper
# ---------------------------------------------------------------------------


class TestThinkingInjection:
    """Test that the wrapper correctly injects extra_body.thinking."""

    def test_thinking_disabled_injection(self):
        """When thinking_mode=False, wrapper injects extra_body.thinking.type='disabled'."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        call_data = _call_data_for(model)

        _wrap_unified_call_with_thinking(call_data, enabled=False, profile="test._reader")

        # Invoke the wrapped unified_call
        _run(call_data["model"].unified_call())
        assert received, "unified_call was not called"
        assert received[0].get("extra_body") == {"thinking": {"type": "disabled"}}

    def test_thinking_enabled_injection(self):
        """When thinking_mode=True, wrapper injects extra_body.thinking.type='enabled'."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        call_data = _call_data_for(model)

        _wrap_unified_call_with_thinking(call_data, enabled=True, profile="test._reader")

        _run(call_data["model"].unified_call())
        assert received
        assert received[0].get("extra_body") == {"thinking": {"type": "enabled"}}

    def test_idempotent_does_not_overwrite_existing_thinking(self):
        """If extra_body.thinking is already set, the wrapper does NOT overwrite it."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        call_data = _call_data_for(model)

        _wrap_unified_call_with_thinking(call_data, enabled=False, profile="test._reader")

        # Invoke with existing extra_body.thinking already set
        _run(call_data["model"].unified_call(extra_body={"thinking": {"type": "enabled"}}))
        assert received
        # Should NOT be overwritten to "disabled"
        assert received[0]["extra_body"]["thinking"]["type"] == "enabled"

    def test_wrapper_installed_on_instance_not_globally(self):
        """Wrapper is installed on the model INSTANCE, not globally."""
        model_a, received_a = _make_model("deepseek/deepseek-v4-flash")
        model_b, received_b = _make_model("deepseek/deepseek-v4-flash")

        call_data_a = _call_data_for(model_a)
        _wrap_unified_call_with_thinking(call_data_a, enabled=False, profile="a._reader")

        # model_b should NOT be affected
        _run(model_b.unified_call())
        assert received_b, "model_b.unified_call was not called"
        # model_b never had the patch, so no extra_body injection
        assert received_b[0].get("extra_body") is None


# ---------------------------------------------------------------------------
# Tests: ThinkingModeToggle extension execute()
# ---------------------------------------------------------------------------


class TestThinkingModeToggleExecute:
    """Integration tests for the full extension.execute() path."""

    def test_deepseek_thinking_false_patches_unified_call(self):
        """DeepSeek model + thinking_mode=False → unified_call patched with disabled."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        agent = _make_agent("test._reader", thinking_mode=False)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        # The model's unified_call should now be the wrapper
        _run(call_data["model"].unified_call())
        assert received
        assert received[0].get("extra_body", {}).get("thinking", {}).get("type") == "disabled"

    def test_deepseek_thinking_true_patches_unified_call(self):
        """DeepSeek model + thinking_mode=True → unified_call patched with enabled."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        agent = _make_agent("test._analyzer", thinking_mode=True)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        _run(call_data["model"].unified_call())
        assert received
        assert received[0].get("extra_body", {}).get("thinking", {}).get("type") == "enabled"

    def test_non_deepseek_model_no_injection_no_crash(self):
        """Non-DeepSeek model + thinking_mode=False → no injection, no crash."""
        model, received = _make_model("anthropic/claude-sonnet-4")
        original_unified_call = model.unified_call
        agent = _make_agent("test._reader", thinking_mode=False)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        # Must not raise
        _run(ext.execute(call_data=call_data))

        # unified_call should NOT be patched for non-DeepSeek
        assert call_data["model"].unified_call is original_unified_call

    def test_no_thinking_mode_set_no_injection(self):
        """Agent with thinking_mode=None (absent field) → no injection, brain preserved."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        original_unified_call = model.unified_call
        agent = _make_agent("trade_auditor_agent", thinking_mode=None)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        # unified_call must NOT be patched
        assert call_data["model"].unified_call is original_unified_call

    def test_call_data_none_is_graceful_noop(self):
        """call_data=None must not raise."""
        agent = _make_agent("test._reader", thinking_mode=False)
        ext = ThinkingModeToggle(agent=agent)
        _run(ext.execute(call_data=None))  # must not raise

    def test_agent_none_is_graceful_noop(self):
        """agent=None must not raise."""
        model, _ = _make_model("deepseek/deepseek-v4-flash")
        ext = ThinkingModeToggle(agent=None)
        call_data = _call_data_for(model)
        _run(ext.execute(call_data=call_data))  # must not raise

    def test_model_identifier_absent_no_injection(self):
        """Model with no model_name → _is_deepseek_model('') is False → no injection."""
        model = MagicMock()
        model.model_name = ""
        original_unified_call = model.unified_call
        agent = _make_agent("test._reader", thinking_mode=False)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        # No injection for unknown model
        assert call_data["model"].unified_call is original_unified_call

    def test_idempotent_does_not_overwrite_via_extension(self):
        """Extension wrapper is idempotent: existing extra_body.thinking not overwritten."""
        model, received = _make_model("deepseek/deepseek-v4-flash")
        agent = _make_agent("test._reader", thinking_mode=False)
        ext = ThinkingModeToggle(agent=agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        # Caller provides extra_body.thinking already set to "enabled"
        _run(call_data["model"].unified_call(extra_body={"thinking": {"type": "enabled"}}))
        assert received
        assert received[0]["extra_body"]["thinking"]["type"] == "enabled"  # NOT overwritten


# ---------------------------------------------------------------------------
# Brain preservation: real brain profiles → no injection
# ---------------------------------------------------------------------------


class TestBrainPreservationExtension:
    """Brain profiles must have thinking_mode=None → extension is a no-op."""

    @pytest.mark.parametrize("brain_profile", [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ])
    def test_brain_profile_no_thinking_injection(self, brain_profile):
        """Real brain YAML (no thinking_mode) → extension leaves unified_call untouched."""
        from unittest.mock import patch
        from helpers import subagents

        model, received = _make_model("deepseek/deepseek-v4-flash")
        original_unified_call = model.unified_call

        # Use REAL subagent data from disk
        real_agent = MagicMock()
        real_agent.config = MagicMock()
        real_agent.config.profile = brain_profile
        real_agent.data = {}  # no cache — let it load from disk

        ext = ThinkingModeToggle(agent=real_agent)
        call_data = _call_data_for(model)

        _run(ext.execute(call_data=call_data))

        # unified_call must NOT be patched for brain agents
        assert call_data["model"].unified_call is original_unified_call, (
            f"BRAIN PRESERVATION VIOLATED: {brain_profile!r} has thinking_mode set "
            "and the extension patched unified_call. Brain agents must NOT have "
            "thinking_mode in their top-level agent.yaml."
        )
