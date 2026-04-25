"""
Tests for CostCalculator per-model pricing.

Tests cost calculation with model-specific pricing YAML.
"""
import pytest
from pathlib import Path
from core.boundary.cost_calculator import CostCalculator


class TestCostCalculator:
    """Test suite for CostCalculator."""

    @pytest.fixture
    def pricing_yaml_path(self):
        """Path to model_pricing.yaml."""
        vm107_root = Path(__file__).parent.parent.parent
        return str(vm107_root / "config" / "model_pricing.yaml")

    def test_known_model_cost(self, pricing_yaml_path):
        """DeepSeek V3 with 1000 input + 500 output tokens returns correct cost."""
        calc = CostCalculator(pricing_yaml_path)
        cost = calc.calculate_cost("deepseek/deepseek-chat", input_tokens=1000, output_tokens=500)

        # (1000 / 1000 * 0.00014) + (500 / 1000 * 0.00028)
        # = 0.00014 + 0.00014 = 0.00028
        assert abs(cost - 0.00028) < 0.0000001

    def test_ollama_free(self, pricing_yaml_path):
        """Ollama models return $0.00."""
        calc = CostCalculator(pricing_yaml_path)
        cost = calc.calculate_cost("ollama/llama3", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_unknown_model_zero_cost(self, pricing_yaml_path, caplog):
        """Unknown model returns $0.00 with warning log."""
        calc = CostCalculator(pricing_yaml_path)
        cost = calc.calculate_cost("unknown/model-x", input_tokens=1000, output_tokens=500)
        assert cost == 0.0
        assert "unknown model" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_provider_prefix_stripping(self, pricing_yaml_path):
        """openai/gpt-4o extracts gpt-4o for pricing lookup."""
        calc = CostCalculator(pricing_yaml_path)

        # Try full name first (should work)
        cost = calc.calculate_cost("openai/gpt-4o", input_tokens=1000, output_tokens=500)

        # (1000 / 1000 * 0.0025) + (500 / 1000 * 0.01)
        # = 0.0025 + 0.005 = 0.0075
        assert abs(cost - 0.0075) < 0.0000001

    def test_zero_tokens(self, pricing_yaml_path):
        """0 tokens returns $0.00."""
        calc = CostCalculator(pricing_yaml_path)
        cost = calc.calculate_cost("deepseek/deepseek-chat", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_yaml_loading(self, pricing_yaml_path):
        """Pricing YAML loads and validates all expected models."""
        calc = CostCalculator(pricing_yaml_path)

        # Check that all expected models are present
        expected_models = [
            "deepseek/deepseek-chat",
            "gemini/gemini-2.0-flash",
            "anthropic/claude-sonnet-4-20250514",
            "openai/gpt-4o",
        ]

        for model in expected_models:
            input_rate, output_rate = calc.get_model_rates(model)
            assert input_rate >= 0.0
            assert output_rate >= 0.0

    def test_get_model_rates(self, pricing_yaml_path):
        """get_model_rates returns (input_per_1k, output_per_1k) tuple."""
        calc = CostCalculator(pricing_yaml_path)
        input_rate, output_rate = calc.get_model_rates("deepseek/deepseek-chat")
        assert input_rate == 0.00014
        assert output_rate == 0.00028
