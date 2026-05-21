"""Phase 62.1 — BUG-13 invoker unit tests: JSON extraction from prose-wrapped text.

BUG-13 (Phase 62.1, Plan 03): When the LLM wraps the JSON payload inside prose
(e.g. a markdown explanation followed by a JSON block), the invoker now extracts
the outermost {...} block before falling through to the _unwrapped_prose sentinel.

These tests verify the 4 observable behaviors of the extraction guard:
  1. Pure JSON in tool_args.text → invoker returns parsed dict (baseline preserved)
  2. Prose-wrapped JSON → invoker extracts and returns the JSON dict
  3. Prose-wrapped JSON → invoker logs a WARNING when extraction fires
  4. Pure prose (no {...} block) → invoker returns _unwrapped_prose sentinel
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Stub out the 'agent' module (Agent Zero runtime) before importing the invoker
# so tests can run without a live Agent Zero install.
_fake_agent_module = MagicMock()
_fake_agent_module.UserMessage = MagicMock(side_effect=lambda message, attachments: MagicMock())
sys.modules.setdefault("agent", _fake_agent_module)

from helpers.mentor_subordinate_invoker import invoke_mentor_subordinate  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_fake_subordinate(monologue_return: str) -> MagicMock:
    """Build a minimal fake subordinate that returns the given string from monologue().

    The fake matches the _SubordinateLike structural protocol:
      - monologue() -> coroutine that returns str
      - hist_add_user_message() -> no-op
      - history.new_topic() -> no-op
      - data dict for _outbound_headers injection
    """
    fake = MagicMock()
    fake.monologue = AsyncMock(return_value=monologue_return)
    fake.hist_add_user_message = MagicMock()
    fake.history = MagicMock()
    fake.history.new_topic = MagicMock()
    fake.data = {}
    return fake


def _make_input() -> MagicMock:
    """Minimal Pydantic-like input model for the invoker."""
    inp = MagicMock()
    inp.model_dump_json.return_value = '{"execution_id": "test-exec-001"}'
    return inp


def _run(coro):
    """Run a coroutine in the test thread."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test 1: baseline — pure JSON in tool_args.text → returns parsed dict
# ---------------------------------------------------------------------------

def test_invoker_returns_parsed_dict_when_text_is_pure_json():
    """invoke_mentor_subordinate returns a parsed dict when response text is pure JSON.

    The monologue returns a well-formed response-tool JSON wrapper with pure JSON
    in tool_args.text. The invoker must unwrap and return the inner parsed dict.
    """
    inner_payload = {
        "schema_version": "1.0",
        "execution_id": "test-exec-001",
        "scope_context": {},
        "retrieved_evidence": {},
        "suspicious_payload": [],
    }
    monologue_str = json.dumps({
        "tool_name": "response",
        "tool_args": {
            "text": json.dumps(inner_payload),
        },
    })

    fake_sub = _make_fake_subordinate(monologue_str)

    # Patch UserMessage and _SUBORDINATE_FACTORY
    with patch("helpers.mentor_subordinate_invoker._SUBORDINATE_FACTORY", return_value=fake_sub):
        result = _run(invoke_mentor_subordinate(
            "trade_auditor_agent._reader",
            _make_input(),
        ))

    assert isinstance(result, dict), "expected dict from pure-JSON path"
    assert result.get("schema_version") == "1.0"
    assert result.get("execution_id") == "test-exec-001"
    # Must NOT be the prose sentinel
    assert "_unwrapped_prose" not in result


# ---------------------------------------------------------------------------
# Test 2: extraction guard — prose-wrapped JSON → returns parsed dict
# ---------------------------------------------------------------------------

def test_invoker_extracts_json_block_from_prose_wrapped_text():
    """invoke_mentor_subordinate extracts JSON from prose-wrapped LLM output.

    Observed LLM behavior: DeepSeek emits a markdown explanation followed by
    the JSON payload wrapped in prose, e.g.:
        "Here's the trade audit result:\\n\\n{\"schema_version\": \"1.0\", ...} Done."

    Expected behavior: invoker extracts the outermost {...} block, parses it,
    and returns the dict instead of the _unwrapped_prose sentinel.
    """
    inner_payload = {
        "schema_version": "1.0",
        "execution_id": "test-exec-002",
        "scope_context": {"profile_id": "trade_auditor_agent"},
        "retrieved_evidence": {"analytics_snapshot": {"result_r": 2.1}},
        "suspicious_payload": [],
    }
    # LLM wraps the JSON in prose within tool_args.text
    prose_wrapped_text = (
        "Here is the evidence retrieval result for your trade audit:\n\n"
        + json.dumps(inner_payload)
        + "\n\nAll tools called successfully."
    )
    monologue_str = json.dumps({
        "tool_name": "response",
        "tool_args": {
            "text": prose_wrapped_text,  # This is NOT valid JSON on its own
        },
    })

    fake_sub = _make_fake_subordinate(monologue_str)

    with patch("helpers.mentor_subordinate_invoker._SUBORDINATE_FACTORY", return_value=fake_sub):
        result = _run(invoke_mentor_subordinate(
            "trade_auditor_agent._reader",
            _make_input(),
        ))

    assert isinstance(result, dict), "expected dict from extraction-guard path"
    assert result.get("schema_version") == "1.0"
    assert result.get("execution_id") == "test-exec-002"
    # Must NOT be the prose sentinel
    assert "_unwrapped_prose" not in result, (
        "Extraction guard must have recovered the JSON block; "
        "sentinel should NOT be returned when a valid {...} block exists."
    )


# ---------------------------------------------------------------------------
# Test 3: warning log — extraction guard logs WARNING when it fires
# ---------------------------------------------------------------------------

def test_invoker_logs_warning_on_extraction_fallback(caplog):
    """invoke_mentor_subordinate logs a WARNING when JSON extraction fallback fires.

    The warning provides observability that the LLM is not following the strict
    JSON output contract. Useful for detecting prompt drift across deployments.
    """
    inner_payload = {
        "schema_version": "1.0",
        "execution_id": "test-exec-003",
        "scope_context": {},
        "retrieved_evidence": {},
        "suspicious_payload": [],
    }
    prose_wrapped_text = (
        "The reader stage has completed. Here is the output: "
        + json.dumps(inner_payload)
        + " End of output."
    )
    monologue_str = json.dumps({
        "tool_name": "response",
        "tool_args": {"text": prose_wrapped_text},
    })

    fake_sub = _make_fake_subordinate(monologue_str)

    with patch("helpers.mentor_subordinate_invoker._SUBORDINATE_FACTORY", return_value=fake_sub), \
         caplog.at_level(logging.WARNING, logger="fingpt.mentor.subordinate_invoker"):
        result = _run(invoke_mentor_subordinate(
            "trade_auditor_agent._reader",
            _make_input(),
        ))

    # Verify the extraction succeeded (not sentinel)
    assert "_unwrapped_prose" not in result

    # Verify WARNING was logged
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("BUG-13 extraction guard fired" in msg for msg in warning_messages), (
        f"Expected WARNING containing 'BUG-13 extraction guard fired' but got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# Test 4: sentinel path — pure prose with no {...} block → _unwrapped_prose
# ---------------------------------------------------------------------------

def test_invoker_returns_unwrapped_prose_sentinel_when_no_json_block():
    """invoke_mentor_subordinate returns _unwrapped_prose sentinel when no JSON block exists.

    When tool_args.text is pure prose with NO embedded {...} block, the extraction
    guard finds nothing to extract and falls through to the existing sentinel path.
    The sentinel must still fire correctly — this is the backward-compat baseline.
    """
    pure_prose_text = (
        "I have completed the evidence retrieval. The trade showed strong momentum "
        "with a positive R-value. Entry was at a key support level. "
        "No significant adversarial content detected. "
        "All tools were called successfully without errors."
        # Intentionally no JSON block — pure prose
    )
    monologue_str = json.dumps({
        "tool_name": "response",
        "tool_args": {"text": pure_prose_text},
    })

    fake_sub = _make_fake_subordinate(monologue_str)

    with patch("helpers.mentor_subordinate_invoker._SUBORDINATE_FACTORY", return_value=fake_sub):
        result = _run(invoke_mentor_subordinate(
            "trade_auditor_agent._reader",
            _make_input(),
        ))

    # Must return the _unwrapped_prose sentinel
    assert "_unwrapped_prose" in result, (
        "Sentinel path must fire when tool_args.text has no recoverable JSON block."
    )
    assert result["_unwrapped_prose"] == pure_prose_text, (
        "Sentinel must preserve the original prose text verbatim."
    )
    assert "_orig_tool_call" in result, (
        "Sentinel must preserve the original tool call for debugging."
    )
