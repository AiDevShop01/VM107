"""
Per-model cost calculation using YAML pricing table.

Supports all major LLM providers with per-model input/output rates.
"""
import yaml
import logging
from typing import Optional

logger = logging.getLogger("boundary.cost")


class CostCalculator:
    """Calculate LLM costs from model pricing YAML."""

    def __init__(self, pricing_yaml_path: str):
        """
        Initialize cost calculator with pricing YAML.

        Args:
            pricing_yaml_path: Path to model_pricing.yaml
        """
        with open(pricing_yaml_path) as f:
            self._config = yaml.safe_load(f)

        self._models = self._config.get("models", {})
        self._default = self._config.get("default", {})

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

        Args:
            model_name: Model identifier

        Returns:
            Tuple of (input_per_1k, output_per_1k) in USD
        """
        # Try exact match first
        if model_name in self._models:
            rates = self._models[model_name]
            return (rates["input_per_1k"], rates["output_per_1k"])

        # Check for Ollama wildcard match
        if model_name.startswith("ollama/"):
            ollama_rates = self._models.get("ollama/*", {})
            if ollama_rates:
                return (ollama_rates["input_per_1k"], ollama_rates["output_per_1k"])

        # Try stripped name (remove provider prefix)
        if "/" in model_name:
            stripped = model_name.split("/", 1)[1]
            if stripped in self._models:
                rates = self._models[stripped]
                return (rates["input_per_1k"], rates["output_per_1k"])

        # Unknown model - log warning and return default ($0.00)
        logger.warning(f"Unknown model '{model_name}', using default pricing ($0.00)")
        return (
            self._default.get("input_per_1k", 0.0),
            self._default.get("output_per_1k", 0.0)
        )
