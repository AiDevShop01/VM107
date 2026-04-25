"""
Tests for CostCalculator with LiteLLM pricing + optional YAML overrides.
"""
import pytest
from unittest.mock import patch
from core.boundary.cost_calculator import CostCalculator, _LITELLM_COSTS

# Skip LiteLLM-dependent tests if litellm is not installed
HAS_LITELLM = len(_LITELLM_COSTS) > 0


class TestCostCalculator:
    """Test suite for CostCalculator."""

    def test_ollama_free(self):
        """Ollama models return $0.00 (local inference)."""
        calc = CostCalculator()
        cost = calc.calculate_cost("ollama/llama3", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_ollama_any_model_free(self):
        """Any ollama/ prefixed model is free."""
        calc = CostCalculator()
        assert calc.get_model_rates("ollama/anything") == (0.0, 0.0)
        assert calc.get_model_rates("ollama/deepseek-v4-flash") == (0.0, 0.0)

    def test_unknown_model_zero_cost(self):
        """Truly unknown model returns $0.00."""
        calc = CostCalculator()
        cost = calc.calculate_cost("fake-provider/nonexistent-model-xyz", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_zero_tokens(self):
        """0 tokens returns $0.00 without even looking up rates."""
        calc = CostCalculator()
        cost = calc.calculate_cost("deepseek/deepseek-chat", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_yaml_override_takes_precedence(self, tmp_path):
        """YAML override rates beat LiteLLM for the same model."""
        yaml_file = tmp_path / "pricing.yaml"
        yaml_file.write_text(
            "models:\n"
            "  deepseek/deepseek-chat:\n"
            "    input_per_1k: 99.0\n"
            "    output_per_1k: 99.0\n"
        )
        calc = CostCalculator(str(yaml_file))
        input_rate, output_rate = calc.get_model_rates("deepseek/deepseek-chat")
        assert input_rate == 99.0
        assert output_rate == 99.0

    def test_no_yaml_works(self):
        """CostCalculator works without any YAML file."""
        calc = CostCalculator()
        # Should not raise
        cost = calc.calculate_cost("ollama/test", input_tokens=100, output_tokens=50)
        assert cost == 0.0

    def test_rates_from_litellm_conversion(self):
        """_rates_from_litellm converts per-token to per-1K correctly."""
        with patch.dict("core.boundary.cost_calculator._LITELLM_COSTS", {
            "test-model": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        }):
            input_rate, output_rate = CostCalculator._rates_from_litellm("test-model")
            assert input_rate == 1.0   # 0.001 * 1000
            assert output_rate == 2.0  # 0.002 * 1000

    def test_litellm_lookup_via_mock(self):
        """LiteLLM lookup works when model_cost is populated."""
        with patch.dict("core.boundary.cost_calculator._LITELLM_COSTS", {
            "deepseek/deepseek-chat": {"input_cost_per_token": 0.00014, "output_cost_per_token": 0.00028}
        }):
            calc = CostCalculator()
            input_rate, output_rate = calc.get_model_rates("deepseek/deepseek-chat")
            assert input_rate == pytest.approx(0.14)
            assert output_rate == pytest.approx(0.28)

    def test_provider_prefix_stripping_via_mock(self):
        """Stripped provider prefix finds model in LiteLLM."""
        with patch.dict("core.boundary.cost_calculator._LITELLM_COSTS", {
            "gpt-4o": {"input_cost_per_token": 0.0025, "output_cost_per_token": 0.01}
        }):
            calc = CostCalculator()
            cost = calc.calculate_cost("openai/gpt-4o", input_tokens=1000, output_tokens=500)
            assert cost > 0.0

    @pytest.mark.skipif(not HAS_LITELLM, reason="litellm not installed")
    def test_litellm_has_many_models(self):
        """LiteLLM pricing database has substantial coverage."""
        assert len(_LITELLM_COSTS) > 100

    @pytest.mark.skipif(not HAS_LITELLM, reason="litellm not installed")
    def test_litellm_real_model_lookup(self):
        """Real LiteLLM lookup returns pricing for known model."""
        calc = CostCalculator()
        input_rate, output_rate = calc.get_model_rates("deepseek/deepseek-chat")
        assert input_rate > 0.0
        assert output_rate > 0.0
