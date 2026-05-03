"""Phase 43.2 Plan 03 — core/agents/structured_output.py unit tests.

Wave 0 status: xfail. Plan 03 implements + removes markers to bring tests GREEN.

Coverage map:
  TestModule    -> STRUCTURED-IO-MODULE-01 (bind_structured + invoke_structured_or_freetext)
  TestSafeParse -> STRUCTURED-IO-FALLBACK-01 (3-stage pipeline)
  TestNormalize -> STRUCTURED-IO-NORMALIZE-01 (content shape variants)
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel


pytestmark = pytest.mark.xfail(
    reason="Wave 0 scaffold — Plan 03 implements structured_output + removes this marker.",
    strict=True,
)


class _SampleSchema(BaseModel):
    field: str
    value: int


class TestModule:
    """STRUCTURED-IO-MODULE-01: bind_structured + invoke_structured_or_freetext primitives."""

    def test_bind_structured_returns_wrapped_llm_when_supported(self):
        """LLM that supports with_structured_output -> bind_structured returns wrapped LLM."""
        raise NotImplementedError

    def test_bind_structured_returns_none_when_unsupported(self):
        """LLM without with_structured_output -> bind_structured returns None + WARNING log."""
        raise NotImplementedError

    def test_invoke_structured_falls_back_to_plain_on_failure(self):
        """structured.invoke raises -> falls through to plain_llm.invoke + WARNING log."""
        raise NotImplementedError


class TestSafeParse:
    """STRUCTURED-IO-FALLBACK-01: 3-stage never-raising parse pipeline."""

    def test_safe_parse_never_raises_on_any_input(self):
        """Property-style: feed garbage, prose, partial JSON, empty -> NEVER raises."""
        from core.agents.structured_output import safe_parse, PlainTextResult
        for bad_input in ["", "not json", "{{{", "<<<>>>", '{"missing": close', None]:
            result = safe_parse(bad_input or "", _SampleSchema)
            # Either parses (won't for these inputs) OR returns PlainTextResult
            assert isinstance(result, (_SampleSchema, PlainTextResult))

    def test_stage1_strict_on_valid_json(self):
        """Valid JSON matching schema -> Stage 1 returns schema instance, not PlainTextResult."""
        raise NotImplementedError

    def test_stage2_repair_handles_trailing_comma(self):
        """JSON with trailing comma -> Stage 1 fails -> Stage 2 repairs -> schema instance."""
        raise NotImplementedError

    def test_stage2_repair_handles_markdown_fence(self):
        """JSON wrapped in ```json fences -> Stage 2 extracts -> schema instance."""
        raise NotImplementedError

    def test_stage3_plain_text_on_prose(self):
        """Pure prose response -> both stages fail -> PlainTextResult(degraded=True, error_chain populated)."""
        raise NotImplementedError


class TestNormalize:
    """STRUCTURED-IO-NORMALIZE-01: content normalization across response shapes."""

    def test_normalize_string_content_passes_through(self):
        """response.content as plain string -> returned unchanged."""
        raise NotImplementedError

    def test_normalize_typed_block_list_openai_responses_api(self):
        """response.content as [{'type': 'text', 'text': '...'}, ...] -> joined string."""
        raise NotImplementedError

    def test_normalize_anthropic_content_blocks(self):
        """Anthropic [{'type': 'text', 'text': '...'}] format -> joined string."""
        raise NotImplementedError

    def test_normalize_handles_edge_cases_without_raising(self):
        """Empty list, None, missing keys -> returns string (possibly empty), never raises."""
        raise NotImplementedError
