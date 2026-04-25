"""
Token counting with three-tier fallback strategy.

Tier 1: LiteLLM usage metadata (exact, zero overhead)
Tier 2: tiktoken cl100k_base (accurate fallback)
Tier 3: word-count estimation (last resort)
"""
from typing import Optional


def count_tokens_tiktoken(text: str) -> int:
    """
    Count tokens using tiktoken cl100k_base encoding.

    Extracted into separate function so tests can mock import failure.
    """
    from helpers.tokens import count_tokens
    return count_tokens(text, encoding_name="cl100k_base")


class TokenCounter:
    """Three-tier token counting: LiteLLM -> tiktoken -> word-count."""

    def count_tokens(
        self,
        text: str,
        usage_metadata: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> int:
        """
        Count tokens using cascading strategy.

        Args:
            text: Text to count tokens for
            usage_metadata: LiteLLM API response usage dict
            model_name: Model name for tokenizer selection (future use)

        Returns:
            Token count (int)
        """
        # Handle empty text
        if not text:
            return 0

        # Tier 1: LiteLLM API response (exact, zero overhead)
        if usage_metadata:
            if "total_tokens" in usage_metadata:
                return usage_metadata["total_tokens"]

            # Also accept separate prompt_tokens + completion_tokens
            if "prompt_tokens" in usage_metadata and "completion_tokens" in usage_metadata:
                return usage_metadata["prompt_tokens"] + usage_metadata["completion_tokens"]

        # Tier 2: tiktoken (offline, accurate)
        try:
            return count_tokens_tiktoken(text)
        except (ImportError, Exception):
            pass

        # Tier 3: Word-count estimation (last resort)
        return int(len(text.split()) * 1.3)

    def count_from_response(
        self,
        prompt_text: str,
        response_text: str,
        usage_metadata: Optional[dict] = None
    ) -> tuple[int, int]:
        """
        Count tokens for prompt and response separately.

        Args:
            prompt_text: User prompt text
            response_text: LLM response text
            usage_metadata: LiteLLM usage dict (if available)

        Returns:
            Tuple of (input_tokens, output_tokens)
        """
        if usage_metadata:
            input_tokens = usage_metadata.get("prompt_tokens", 0)
            output_tokens = usage_metadata.get("completion_tokens", 0)

            # If usage metadata present but incomplete, fall back to counting
            if input_tokens == 0 and output_tokens == 0:
                input_tokens = self.count_tokens(prompt_text, usage_metadata=None)
                output_tokens = self.count_tokens(response_text, usage_metadata=None)

            return (input_tokens, output_tokens)

        # No usage metadata - count both separately
        input_tokens = self.count_tokens(prompt_text, usage_metadata=None)
        output_tokens = self.count_tokens(response_text, usage_metadata=None)

        return (input_tokens, output_tokens)
