"""Phase 43.2 Plan 03 — core/agents/structured_output.py unit tests.

Coverage map:
  TestModule    -> STRUCTURED-IO-MODULE-01 (bind_structured + invoke_structured_or_freetext)
  TestSafeParse -> STRUCTURED-IO-FALLBACK-01 (3-stage pipeline)
  TestNormalize -> STRUCTURED-IO-NORMALIZE-01 (content shape variants)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel

from core.agents.structured_output import (
    bind_structured,
    invoke_structured_or_freetext,
    normalize_content,
    safe_parse,
    PlainTextResult,
)


class _SampleSchema(BaseModel):
    field: str
    value: int


class TestModule:
    """STRUCTURED-IO-MODULE-01: bind_structured + invoke_structured_or_freetext primitives."""

    def test_bind_structured_returns_wrapped_llm_when_supported(self):
        """LLM that supports with_structured_output -> bind_structured returns wrapped LLM."""
        mock_llm = MagicMock()
        wrapped = MagicMock()
        mock_llm.with_structured_output.return_value = wrapped
        result = bind_structured(mock_llm, _SampleSchema, "test_agent")
        assert result is wrapped
        mock_llm.with_structured_output.assert_called_once_with(_SampleSchema)

    def test_bind_structured_returns_none_when_unsupported(self, caplog):
        """LLM without with_structured_output -> bind_structured returns None + WARNING log."""
        import logging
        mock_llm = MagicMock()
        mock_llm.with_structured_output.side_effect = AttributeError("not supported")
        with caplog.at_level(logging.WARNING, logger="agents.structured_output"):
            result = bind_structured(mock_llm, _SampleSchema, "test_agent")
        assert result is None
        assert any("structured_bind_unsupported" in r.message for r in caplog.records)

    def test_invoke_structured_falls_back_to_plain_on_failure(self, caplog):
        """structured.invoke raises -> falls through to plain_llm.invoke + WARNING log."""
        import logging
        structured = MagicMock()
        structured.invoke.side_effect = Exception("malformed json")
        plain = MagicMock()
        plain.invoke.return_value = "fallback response"
        with caplog.at_level(logging.WARNING, logger="agents.structured_output"):
            result = invoke_structured_or_freetext(
                structured, plain, "prompt", str, "test_agent"
            )
        assert result == "fallback response"
        assert any(
            "structured_invoke_failed_falling_to_plain" in r.message
            for r in caplog.records
        )


class TestSafeParse:
    """STRUCTURED-IO-FALLBACK-01: 3-stage never-raising parse pipeline."""

    def test_safe_parse_never_raises_on_any_input(self):
        """Property-style: feed garbage, prose, partial JSON, empty -> NEVER raises."""
        for bad_input in ["", "not json", "{{{", "<<<>>>", '{"missing": close', None]:
            result = safe_parse(bad_input or "", _SampleSchema)
            # Either parses (won't for these inputs) OR returns PlainTextResult
            assert isinstance(result, (_SampleSchema, PlainTextResult))

    def test_stage1_strict_on_valid_json(self):
        """Valid JSON matching schema -> Stage 1 returns schema instance, not PlainTextResult."""
        result = safe_parse('{"field": "x", "value": 1}', _SampleSchema)
        assert isinstance(result, _SampleSchema)
        assert result.field == "x"
        assert result.value == 1

    def test_stage2_repair_handles_trailing_comma(self):
        """JSON with trailing comma -> Stage 1 fails -> Stage 2 repairs -> schema instance."""
        result = safe_parse('{"field": "x", "value": 1,}', _SampleSchema)
        assert isinstance(result, _SampleSchema)
        assert result.field == "x"

    def test_stage2_repair_handles_markdown_fence(self):
        """JSON wrapped in ```json fences -> Stage 2 extracts -> schema instance."""
        wrapped = '```json\n{"field": "x", "value": 1}\n```'
        result = safe_parse(wrapped, _SampleSchema)
        assert isinstance(result, _SampleSchema)

    def test_stage3_plain_text_on_prose(self):
        """Pure prose response -> both stages fail -> PlainTextResult(degraded=True, error_chain populated)."""
        result = safe_parse(
            "I think the answer is probably 42, but I'm not sure.", _SampleSchema
        )
        assert isinstance(result, PlainTextResult)
        assert result.degraded is True
        assert len(result.error_chain) >= 1
        assert "stage_1_strict" in result.error_chain[0]


class TestNormalize:
    """STRUCTURED-IO-NORMALIZE-01: content normalization across response shapes."""

    def test_normalize_string_content_passes_through(self):
        """response.content as plain string -> returned unchanged."""
        resp = MagicMock()
        resp.content = "hello"
        assert normalize_content(resp) == "hello"

    def test_normalize_typed_block_list_openai_responses_api(self):
        """response.content as [{'type': 'text', 'text': '...'}, ...] -> joined string (reasoning blocks skipped)."""
        resp = MagicMock()
        resp.content = [
            {"type": "reasoning", "reasoning": "thinking..."},
            {"type": "text", "text": "answer is 42"},
        ]
        assert normalize_content(resp) == "answer is 42"

    def test_normalize_anthropic_content_blocks(self):
        """Anthropic [{'type': 'text', 'text': '...'}] format -> joined string."""
        resp = MagicMock()
        resp.content = [{"type": "text", "text": "hi"}, {"type": "text", "text": " world"}]
        assert normalize_content(resp) == "hi world"

    def test_normalize_handles_edge_cases_without_raising(self):
        """Empty list, None, missing keys -> returns string (possibly empty), never raises."""
        resp = MagicMock()
        resp.content = None
        assert normalize_content(resp) == ""
        resp.content = []
        assert normalize_content(resp) == ""
        resp.content = [{}, {"type": "text"}]  # missing text key -> empty string for that block
        result = normalize_content(resp)
        assert isinstance(result, str)  # should not raise; returns ""
