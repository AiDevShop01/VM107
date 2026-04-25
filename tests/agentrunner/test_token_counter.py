"""
Tests for TokenCounter three-tier token counting.

Tests the cascading token counting strategy:
- Tier 1: LiteLLM usage metadata (exact)
- Tier 2: tiktoken fallback
- Tier 3: word-count estimation
"""
import pytest
from unittest.mock import patch, MagicMock
from core.boundary.token_counter import TokenCounter


class TestTokenCounter:
    """Test suite for TokenCounter."""

    def test_tier1_litellm_usage_total(self):
        """When usage_metadata has total_tokens, return exact count."""
        counter = TokenCounter()
        usage = {"total_tokens": 1234}
        result = counter.count_tokens("some text here", usage_metadata=usage)
        assert result == 1234

    def test_tier1_with_prompt_completion(self):
        """When usage_metadata has prompt_tokens + completion_tokens, return sum."""
        counter = TokenCounter()
        usage = {"prompt_tokens": 800, "completion_tokens": 200}
        result = counter.count_tokens("some text", usage_metadata=usage)
        assert result == 1000

    def test_tier2_tiktoken_fallback(self):
        """When usage_metadata is None, uses tiktoken cl100k_base encoding."""
        counter = TokenCounter()
        text = "Hello world this is a test"
        result = counter.count_tokens(text, usage_metadata=None)

        # tiktoken should return a reasonable count (6-8 tokens for this text)
        assert 5 <= result <= 10

    def test_tier3_word_count_fallback(self):
        """When tiktoken import fails, uses len(text.split()) * 1.3."""
        # Mock tiktoken to raise ImportError
        with patch('core.boundary.token_counter.count_tokens_tiktoken', side_effect=ImportError):
            counter = TokenCounter()
            text = "one two three four five"  # 5 words
            result = counter.count_tokens(text, usage_metadata=None)
            # 5 * 1.3 = 6.5 -> int(6.5) = 6
            assert result == 6

    def test_empty_text(self):
        """Returns 0 for empty string."""
        counter = TokenCounter()
        assert counter.count_tokens("", usage_metadata=None) == 0

    def test_count_from_response(self):
        """Helper that takes prompt_text + response_text + usage_metadata returns (input_tokens, output_tokens)."""
        counter = TokenCounter()

        # With usage metadata
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        input_tokens, output_tokens = counter.count_from_response(
            prompt_text="prompt",
            response_text="response",
            usage_metadata=usage
        )
        assert input_tokens == 100
        assert output_tokens == 50

        # Without usage metadata (tiktoken fallback)
        input_tokens, output_tokens = counter.count_from_response(
            prompt_text="hello world",
            response_text="goodbye world",
            usage_metadata=None
        )
        assert input_tokens > 0
        assert output_tokens > 0
