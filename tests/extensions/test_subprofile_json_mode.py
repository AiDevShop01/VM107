"""Phase 62.1 BUG-22 unit tests: SubprofileJsonMode extension infrastructure.

BUG-22 history:
  response_format={"type":"json_object"} was implemented and tested live against
  deepseek/deepseek-v4-flash. The extension infrastructure worked correctly (the
  chat_model_call_before hook fires, the monkey-patch plumbing is correct), but
  the json_object mode itself proved counter-productive:

  - DeepSeek v4-flash in json_object mode emits bare ReaderOutput dicts instead
    of the required {"tool_name": "response", "tool_args": {"text": "..."}} wrapper.
  - This breaks Agent Zero's monologue loop (validate_tool_request raises on bare
    ReaderOutput; response tool returns error prose; monologue() returns non-JSON).

  The extension is kept as a graceful no-op so the plumbing is proven and the
  infrastructure is ready for a future model that correctly handles json_object mode.

Test coverage:
  1. Profile detection: _reader / _analyzer / _writer suffixes identified correctly
  2. Parent profile → not identified as sub-profile
  3. Empty profile → not identified as sub-profile
  4. Extension execute() is a graceful no-op — unified_call is NOT patched
  5. call_data=None → no exception
  6. agent=None → no exception
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from extensions.python.chat_model_call_before._subprofile_json_mode import (  # noqa: E402
    SubprofileJsonMode,
    _profile_is_subprofile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extension(profile: str):
    """Build a SubprofileJsonMode extension with a fake agent at the given profile."""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.profile = profile
    return SubprofileJsonMode(agent=agent)


def _make_model_with_tracker():
    """Return a fake model whose unified_call records kwargs it was called with."""
    received_kwargs: list[dict] = []

    async def _unified_call(**kw):
        received_kwargs.append(dict(kw))
        return ("fake_response", None)

    model = MagicMock()
    model.unified_call = _unified_call
    return model, received_kwargs


def _call_data_for(model) -> dict:
    return {"model": model}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfileIsSubprofile:
    def test_reader_suffix(self):
        assert _profile_is_subprofile("trade_auditor_agent._reader") is True

    def test_analyzer_suffix(self):
        assert _profile_is_subprofile("behavioral_mentor_agent._analyzer") is True

    def test_writer_suffix(self):
        assert _profile_is_subprofile("trade_auditor_agent._writer") is True

    def test_parent_profile_no_match(self):
        assert _profile_is_subprofile("trade_auditor_agent") is False

    def test_empty_profile_no_match(self):
        assert _profile_is_subprofile("") is False

    def test_arbitrary_profile_no_match(self):
        assert _profile_is_subprofile("some_other_agent") is False


class TestSubprofileJsonMode:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_reader_no_injection_noop(self):
        """BUG-22 is a no-op: unified_call must NOT be patched for _reader.

        json_object mode broke deepseek-v4-flash tool-call output (see module docstring).
        The extension is kept for future activation but currently does nothing.
        """
        ext = _make_extension("trade_auditor_agent._reader")
        model, received = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))

        # unified_call must NOT be monkey-patched (no-op implementation)
        assert model.unified_call is original_unified_call, (
            "BUG-22 no-op violated: unified_call was patched but should not be"
        )

    def test_analyzer_no_injection_noop(self):
        """BUG-22 is a no-op: unified_call must NOT be patched for _analyzer."""
        ext = _make_extension("behavioral_mentor_agent._analyzer")
        model, received = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        assert model.unified_call is original_unified_call

    def test_writer_no_injection_noop(self):
        """BUG-22 is a no-op: unified_call must NOT be patched for _writer."""
        ext = _make_extension("trade_auditor_agent._writer")
        model, received = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        assert model.unified_call is original_unified_call

    def test_parent_agent_no_injection(self):
        """Parent agent profile → no-op regardless."""
        ext = _make_extension("trade_auditor_agent")
        model, _ = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        assert model.unified_call is original_unified_call

    def test_empty_profile_no_injection(self):
        """Empty profile → no-op."""
        ext = _make_extension("")
        model, _ = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        assert model.unified_call is original_unified_call

    def test_call_data_none_is_graceful_noop(self):
        """call_data=None must not raise."""
        ext = _make_extension("trade_auditor_agent._reader")
        self._run(ext.execute(call_data=None))  # should not raise

    def test_agent_none_is_graceful_noop(self):
        """agent=None must not raise."""
        ext = SubprofileJsonMode(agent=None)
        model, _ = _make_model_with_tracker()
        self._run(ext.execute(call_data=_call_data_for(model)))  # should not raise
