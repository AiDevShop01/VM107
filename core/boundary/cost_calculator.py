"""
Per-model cost calculation using LiteLLM's pricing database.

Primary source: LiteLLM model_cost (2,600+ models, auto-updated with package).
Override source: YAML pricing file for custom rates or models not in LiteLLM.
Ollama models always $0.00 (local inference).
"""
import logging
from typing import Optional

logger = logging.getLogger("boundary.cost")

# LiteLLM pricing database (loaded once at import time)
try:
    from litellm import model_cost as _LITELLM_COSTS
except ImportError:
    _LITELLM_COSTS = {}


class CostCalculator:
    """Calculate LLM costs from LiteLLM pricing + optional YAML overrides."""

    def __init__(self, pricing_yaml_path: Optional[str] = None):
        """
        Initialize cost calculator.

        Args:
            pricing_yaml_path: Optional path to model_pricing.yaml for overrides.
                             If None, uses LiteLLM pricing only.
        """
        self._overrides: dict = {}

        if pricing_yaml_path:
            try:
                import yaml
                with open(pricing_yaml_path) as f:
                    config = yaml.safe_load(f) or {}
                self._overrides = config.get("models", {})
            except Exception as e:
                logger.warning(f"Failed to load pricing overrides: {e}")

    def calculate_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """
        Calculate cost for a model invocation.

        Args:
            model_name: Model identifier (e.g., "deepseek/deepseek-chat")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD (float)
        """
        if input_tokens == 0 and output_tokens == 0:
            return 0.0

        input_rate, output_rate = self.get_model_rates(model_name)

        cost = (input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate)
        return cost

    def get_model_rates(self, model_name: str) -> tuple[float, float]:
        """
        Get pricing rates for a model.

        Resolution order:
        1. YAML overrides (exact match)
        2. Ollama wildcard ($0.00)
        3. LiteLLM model_cost (exact match)
        4. LiteLLM model_cost (stripped provider prefix)
        5. Default $0.00 with warning

        Args:
            model_name: Model identifier

        Returns:
            Tuple of (input_per_1k, output_per_1k) in USD
        """
        # 1. YAML overrides (exact match)
        if model_name in self._overrides:
            rates = self._overrides[model_name]
            return (rates["input_per_1k"], rates["output_per_1k"])

        # 2. Ollama = free (local inference)
        if model_name.startswith("ollama/"):
            return (0.0, 0.0)

        # 3. LiteLLM exact match
        if model_name in _LITELLM_COSTS:
            return self._rates_from_litellm(model_name)

        # 4. LiteLLM stripped provider prefix
        if "/" in model_name:
            stripped = model_name.split("/", 1)[1]
            if stripped in _LITELLM_COSTS:
                return self._rates_from_litellm(stripped)

            # Also try YAML overrides with stripped name
            if stripped in self._overrides:
                rates = self._overrides[stripped]
                return (rates["input_per_1k"], rates["output_per_1k"])

        # 5. Unknown model
        logger.warning(f"Unknown model '{model_name}', using default pricing ($0.00)")
        return (0.0, 0.0)

    @staticmethod
    def _rates_from_litellm(model_key: str) -> tuple[float, float]:
        """Extract per-1K-token rates from LiteLLM's per-token pricing."""
        info = _LITELLM_COSTS[model_key]
        # LiteLLM stores cost per token, we need per 1K tokens
        input_per_token = info.get("input_cost_per_token", 0.0) or 0.0
        output_per_token = info.get("output_cost_per_token", 0.0) or 0.0
        return (input_per_token * 1000, output_per_token * 1000)
