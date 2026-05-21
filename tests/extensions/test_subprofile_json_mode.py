"""Phase 62.1 BUG-22 unit tests: SubprofileJsonMode extension injects response_format.

The extension injects response_format={"type":"json_object"} into LLM calls made
by sub-profile agents (_reader/_analyzer/_writer) so DeepSeek emits pure JSON
instead of markdown-with-embedded-JSON audit reports.

Test coverage:
  1. Sub-profile _reader → response_format=json_object injected
  2. Sub-profile _analyzer → response_format=json_object injected
  3. Sub-profile _writer → response_format=json_object injected
  4. Parent agent (no sub-profile suffix) → NO injection
  5. Empty profile → NO injection
  6. Explicit response_format already set → honour caller's value (no override)
  7. call_data["model"] has no unified_call → graceful no-op (log warning)
  8. call_data is None → graceful no-op
  9. agent is None → graceful no-op
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_reader_injects_json_object(self):
        """_reader sub-profile call must receive response_format=json_object."""
        ext = _make_extension("trade_auditor_agent._reader")
        model, received = _make_model_with_tracker()
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))

        # After execute(), model.unified_call is patched.
        # Call it and inspect what kwargs it forwarded.
        self._run(model.unified_call(messages=[]))
        assert len(received) == 1
        assert received[0].get("response_format") == {"type": "json_object"}, (
            f"response_format not injected: {received[0]}"
        )

    def test_analyzer_injects_json_object(self):
        """_analyzer sub-profile call must receive response_format=json_object."""
        ext = _make_extension("behavioral_mentor_agent._analyzer")
        model, received = _make_model_with_tracker()
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        self._run(model.unified_call(messages=[]))

        assert received[0].get("response_format") == {"type": "json_object"}

    def test_writer_injects_json_object(self):
        """_writer sub-profile call must receive response_format=json_object."""
        ext = _make_extension("trade_auditor_agent._writer")
        model, received = _make_model_with_tracker()
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        self._run(model.unified_call(messages=[]))

        assert received[0].get("response_format") == {"type": "json_object"}

    def test_parent_agent_no_injection(self):
        """Parent agent (no sub-profile suffix) must NOT get response_format injected."""
        ext = _make_extension("trade_auditor_agent")
        model, received = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))

        # unified_call should NOT be monkey-patched — still the same object
        assert model.unified_call is original_unified_call, (
            "Parent agent unified_call was unexpectedly patched"
        )

    def test_empty_profile_no_injection(self):
        """Empty profile → extension is a no-op."""
        ext = _make_extension("")
        model, received = _make_model_with_tracker()
        original_unified_call = model.unified_call
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))
        assert model.unified_call is original_unified_call

    def test_explicit_response_format_not_overridden(self):
        """If caller already sets response_format, the patch must honour it."""
        ext = _make_extension("trade_auditor_agent._reader")
        model, received = _make_model_with_tracker()
        call_data = _call_data_for(model)

        self._run(ext.execute(call_data=call_data))

        # Caller explicitly sets a different format
        caller_format = {"type": "text"}
        self._run(model.unified_call(messages=[], response_format=caller_format))

        assert received[0].get("response_format") == caller_format, (
            f"Caller's response_format was overridden: {received[0]}"
        )

    def test_model_without_unified_call_is_graceful_noop(self, caplog):
        """If model has no unified_call, extension logs a warning and skips."""
        ext = _make_extension("trade_auditor_agent._reader")
        model = MagicMock(spec=[])  # no unified_call attribute
        call_data = {"model": model}

        with caplog.at_level(logging.WARNING, logger="fingpt.chat_model_call_before.subprofile_json_mode"):
            self._run(ext.execute(call_data=call_data))

        assert any(
            "BUG-22" in r.message for r in caplog.records
        ), f"Expected BUG-22 warning; got: {[r.message for r in caplog.records]}"

    def test_call_data_none_is_graceful_noop(self):
        """call_data=None must not raise."""
        ext = _make_extension("trade_auditor_agent._reader")
        self._run(ext.execute(call_data=None))  # should not raise

    def test_agent_none_is_graceful_noop(self):
        """agent=None must not raise."""
        ext = SubprofileJsonMode(agent=None)
        model, _ = _make_model_with_tracker()
        self._run(ext.execute(call_data=_call_data_for(model)))  # should not raise
