"""
Integration test — proves BUG-23 thinking_mode capability flag actually translates
into the outbound LiteLLM payload. Closes the verification gap from Phase 62.1
Plan 04 production runs.

Approach: patch ``models.acompletion`` (the name as bound in the models module, so
the patch intercepts the call site inside ``LiteLLMChatWrapper.unified_call``) and
then exercise the real extension + wrapper chain to assert the thinking-mode
``extra_body`` is present / absent based on profile config.

This is INTEGRATION, not unit:
  - LiteLLMChatWrapper is instantiated as a real object.
  - ThinkingModeToggle.execute() runs against that real wrapper, installing its
    monkey-patch on the instance's unified_call.
  - models.acompletion is the only thing stubbed (we don't want to hit the network).

The test is designed to run on the host venv (no container required).  Run with:

    cd /Volumes/\\ HardDrive/FinGPT/VM107
    pytest tests/extensions/test_thinking_mode_injection_integration.py -v

Or inside the container:

    docker exec vm107-agent-zero pytest \
        tests/extensions/test_thinking_mode_injection_integration.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Minimal env stubs so models.py and helpers can import without crashing
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

import inspect  # noqa: E402

import models  # noqa: E402  (must be after sys.path and env setup)
from models import LiteLLMChatWrapper  # noqa: E402
from extensions.python.chat_model_call_before._thinking_mode_toggle import (  # noqa: E402
    ThinkingModeToggle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_real_wrapper(provider: str, model: str) -> LiteLLMChatWrapper:
    """Build a real LiteLLMChatWrapper instance (no LLM call will be made)."""
    return LiteLLMChatWrapper(model=model, provider=provider)


def _make_agent(profile: str, thinking_mode: bool | None) -> MagicMock:
    """Build a fake Agent with a pre-cached thinking_mode value.

    Pre-seeding the cache bypasses ``subagents.load_agent_data`` so tests remain
    deterministic and independent of file-system state.  The *brain-preservation*
    cases below use disk loads instead (see ``TestBrainPreservation``).
    """
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.profile = profile
    agent.data = {"_bug23_thinking_cache": {"value": thinking_mode}}
    return agent


async def _run_injection_chain(
    provider: str,
    model: str,
    profile: str,
    thinking_mode: bool | None,
) -> tuple[dict | None, bool]:
    """Exercise the real extension + wrapper chain.

    Returns:
        captured_kw: the kwargs dict received by models.acompletion, or None if
                     acompletion was never called.
        unified_call_was_patched: True if unified_call was replaced by the extension.
    """
    wrapper = _make_real_wrapper(provider=provider, model=model)
    original_unified_call = wrapper.unified_call

    agent = _make_agent(profile=profile, thinking_mode=thinking_mode)
    ext = ThinkingModeToggle(agent=agent)
    call_data = {"model": wrapper}

    # Run the real extension execute() — this is the step that installs (or does
    # not install) the unified_call monkey-patch.
    await ext.execute(call_data=call_data)

    # Detect patching by checking the instance __dict__.
    # Bound methods are re-created on each attribute access (Python descriptor protocol),
    # so ``is`` identity comparisons against a previously-captured bound method are
    # unreliable.  The extension assigns a closure function directly to the instance
    # __dict__ (call_data["model"].unified_call = _unified_call_with_thinking), so the
    # reliable signal is: "unified_call" present in the instance __dict__.
    unified_call_was_patched = "unified_call" in call_data["model"].__dict__

    # Intercept acompletion at the models-module level to capture outbound kwargs.
    captured: list[dict] = []

    async def _fake_acompletion(**kw: Any):
        captured.append(dict(kw))
        # Return a minimal non-streaming fake so unified_call completes without error.
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = ""
        chunk.choices[0].delta.reasoning_content = None
        chunk.usage = None
        return chunk  # non-stream path: unified_call parses this directly

    with patch.object(models, "acompletion", _fake_acompletion):
        try:
            await call_data["model"].unified_call(user_message="ping")
        except Exception:
            # Any exception from result parsing is irrelevant — we only care about
            # what acompletion RECEIVED.
            pass

    captured_kw = captured[0] if captured else None
    return captured_kw, unified_call_was_patched


# ---------------------------------------------------------------------------
# Parameterized integration test
# ---------------------------------------------------------------------------


# fmt: off
_CASES = [
    # (case_id, provider, model, profile, thinking_mode, expect_thinking_type)
    # --- reader sub-profiles (utility tier, thinking off) ---
    (
        "trade_auditor._reader",
        "deepseek", "deepseek-v4-flash",
        "trade_auditor_agent._reader",
        False, "disabled",
    ),
    (
        "behavioral_mentor._reader",
        "deepseek", "deepseek-v4-flash",
        "behavioral_mentor_agent._reader",
        False, "disabled",
    ),
    (
        "weekly_review._reader",
        "deepseek", "deepseek-v4-flash",
        "weekly_review_agent._reader",
        False, "disabled",
    ),
    # --- analyzer sub-profile (chat tier, thinking on) ---
    (
        "trade_auditor._analyzer",
        "deepseek", "deepseek-v4-flash",
        "trade_auditor_agent._analyzer",
        True, "enabled",
    ),
    # --- brain / top-level agents (no thinking_mode field → no injection) ---
    (
        "brain_trade_auditor",
        "deepseek", "deepseek-v4-flash",
        "trade_auditor_agent",
        None, None,   # None means: assert NO extra_body.thinking is injected
    ),
    (
        "brain_behavioral_mentor",
        "deepseek", "deepseek-v4-flash",
        "behavioral_mentor_agent",
        None, None,
    ),
    (
        "brain_weekly_review",
        "deepseek", "deepseek-v4-flash",
        "weekly_review_agent",
        None, None,
    ),
]
# fmt: on


@pytest.mark.parametrize(
    "case_id,provider,model,profile,thinking_mode,expect_thinking_type",
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_thinking_mode_injection_end_to_end(
    case_id,
    provider,
    model,
    profile,
    thinking_mode,
    expect_thinking_type,
):
    """Integration: ThinkingModeToggle.execute() + LiteLLMChatWrapper.unified_call()
    → models.acompletion receives the correct extra_body.

    This test exercises the real extension chain with a real wrapper instance.
    Only models.acompletion is patched (network stub).

    Pass/fail determines whether BUG-23 wiring is correct end-to-end.
    """
    captured_kw, patched = _run(
        _run_injection_chain(
            provider=provider,
            model=model,
            profile=profile,
            thinking_mode=thinking_mode,
        )
    )

    assert captured_kw is not None, (
        f"[{case_id}] models.acompletion was never called — "
        "unified_call did not reach the LiteLLM call site. "
        "This is a fatal wiring break."
    )

    actual_extra_body = captured_kw.get("extra_body", {}) or {}
    actual_thinking = actual_extra_body.get("thinking")

    if expect_thinking_type is None:
        # Brain-preservation case: NO thinking key must be injected.
        assert actual_thinking is None, (
            f"[{case_id}] BRAIN PRESERVATION VIOLATED: "
            f"expected no extra_body.thinking for profile {profile!r} "
            f"(thinking_mode not set), but got extra_body={actual_extra_body!r}. "
            "Brain agents must NOT have thinking_mode in their agent.yaml."
        )
        assert not patched, (
            f"[{case_id}] unified_call was monkey-patched for brain profile {profile!r} "
            "but should not have been (thinking_mode is None)."
        )
    else:
        # Sub-profile case: thinking key MUST be injected with the correct type.
        assert actual_thinking is not None, (
            f"[{case_id}] INJECTION MISSING: expected extra_body.thinking for profile "
            f"{profile!r} (thinking_mode={thinking_mode}), but extra_body={actual_extra_body!r}. "
            "The ThinkingModeToggle extension did not inject the thinking key."
        )
        assert actual_thinking.get("type") == expect_thinking_type, (
            f"[{case_id}] WRONG THINKING TYPE: expected 'type'={expect_thinking_type!r} "
            f"but got {actual_thinking!r} for profile {profile!r}."
        )
        assert patched, (
            f"[{case_id}] unified_call was NOT monkey-patched for sub-profile {profile!r} "
            f"(thinking_mode={thinking_mode}). The extension failed to install the wrapper."
        )

        # Bonus: assert the model name was passed through unchanged.
        assert captured_kw.get("model") == f"{provider}/{model}", (
            f"[{case_id}] model name changed in transit: "
            f"expected {provider}/{model!r}, got {captured_kw.get('model')!r}."
        )


# ---------------------------------------------------------------------------
# Brain-preservation with REAL YAML loads (disk, not pre-cached)
# ---------------------------------------------------------------------------


class TestBrainPreservationRealYaml:
    """Verify that brain profiles have no thinking_mode when loaded from disk.

    These use real subagents.load_agent_data calls to confirm the YAMLs on disk
    match the expected schema (thinking_mode absent / None).
    """

    @pytest.mark.parametrize("brain_profile", [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ])
    def test_brain_yaml_has_no_thinking_mode(self, brain_profile: str):
        """Real YAML load: brain agent.yaml must NOT set thinking_mode."""
        from helpers import subagents

        agent_data = subagents.load_agent_data(brain_profile)
        assert agent_data.thinking_mode is None, (
            f"Brain profile {brain_profile!r} has thinking_mode={agent_data.thinking_mode!r} "
            "in its agent.yaml. Brain agents MUST NOT set thinking_mode — only sub-profiles "
            "should. Remove the field from the top-level agent.yaml."
        )

    @pytest.mark.parametrize("reader_profile", [
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ])
    def test_reader_yaml_has_thinking_mode_false(self, reader_profile: str):
        """Real YAML load: reader sub-profile agent.yaml must set thinking_mode=False."""
        from helpers import subagents

        agent_data = subagents.load_agent_data(reader_profile)
        assert agent_data.thinking_mode is False, (
            f"Reader profile {reader_profile!r} has thinking_mode={agent_data.thinking_mode!r}. "
            "Expected False (BUG-23 contract: readers use utility tier with thinking off)."
        )
