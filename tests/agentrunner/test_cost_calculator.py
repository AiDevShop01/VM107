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


class TestRolling7dAvgSameHour:
    """Tests for CostCalculator.rolling_7d_avg_same_hour (Phase 74 REQ-74-7).

    The method returns the mean hourly cost for a given conversation type
    across the last 7 days at the same UTC hour as target_dt.

    Cold-start sentinel: if fewer than 7 distinct calendar-day records exist
    for the (conv_type, hour) pair, return 0.0 (never a partial average).
    This prevents false-positive anomaly triggers during early history build-up
    (RESEARCH Pitfall 5).
    """

    def _make_calc_with_ledger(self, entries):
        """Build a CostCalculator seeded with synthetic cost_ledger entries.

        entries: list of dicts with keys:
            - conv_type (str)
            - date (datetime.date)
            - hour (int)
            - cost_usd (float)
        """
        from datetime import date as _date
        calc = CostCalculator()
        calc._cost_ledger = entries  # attach synthetic ledger directly
        return calc

    def test_returns_mean_with_7_days_history(self):
        """With exactly 7 days of history, returns the correct mean."""
        from datetime import datetime, timezone, date, timedelta

        target = datetime(2026, 6, 10, 14, 30, 0, tzinfo=timezone.utc)  # 14:xx UTC
        base_date = date(2026, 6, 3)

        entries = [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": float(i + 1)}
            for i in range(7)  # 7 days: June 3–9, hour 14
        ]

        calc = self._make_calc_with_ledger(entries)
        result = calc.rolling_7d_avg_same_hour("research", target)
        # Mean of [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0] = 4.0
        assert result == pytest.approx(4.0)

    def test_cold_start_fewer_than_7_days_returns_zero(self):
        """With < 7 days of history, returns 0.0 (cold-start sentinel, Pitfall 5)."""
        from datetime import datetime, timezone, date, timedelta

        target = datetime(2026, 6, 10, 14, 0, 0, tzinfo=timezone.utc)
        base_date = date(2026, 6, 7)

        entries = [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": 5.0}
            for i in range(3)  # only 3 days — cold start
        ]

        calc = self._make_calc_with_ledger(entries)
        result = calc.rolling_7d_avg_same_hour("research", target)
        assert result == 0.0, (
            "Must return 0.0 sentinel when fewer than 7 days of history exist — "
            "never return a partial/best-effort average (RESEARCH Pitfall 5)"
        )

    def test_no_history_returns_zero(self):
        """With no history at all, returns 0.0 (cold-start sentinel)."""
        from datetime import datetime, timezone

        target = datetime(2026, 6, 10, 14, 0, 0, tzinfo=timezone.utc)
        calc = self._make_calc_with_ledger([])
        result = calc.rolling_7d_avg_same_hour("research", target)
        assert result == 0.0

    def test_conv_type_isolation(self):
        """research history does NOT bleed into execution query."""
        from datetime import datetime, timezone, date, timedelta

        target = datetime(2026, 6, 10, 14, 0, 0, tzinfo=timezone.utc)
        base_date = date(2026, 6, 3)

        # 7 days of research entries at hour 14
        entries = [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": 99.0}
            for i in range(7)
        ]
        # Only 2 days of execution entries at hour 14 (below cold-start threshold)
        entries += [
            {"conv_type": "execution", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": 1.0}
            for i in range(2)
        ]

        calc = self._make_calc_with_ledger(entries)
        # research has 7 days → valid mean
        research_avg = calc.rolling_7d_avg_same_hour("research", target)
        assert research_avg == pytest.approx(99.0)
        # execution has 2 days → cold start sentinel
        execution_avg = calc.rolling_7d_avg_same_hour("execution", target)
        assert execution_avg == 0.0, "execution cold-start must not be contaminated by research history"

    def test_hour_isolation(self):
        """Records at hour 10 do NOT count toward the hour 14 average."""
        from datetime import datetime, timezone, date, timedelta

        target = datetime(2026, 6, 10, 14, 0, 0, tzinfo=timezone.utc)
        base_date = date(2026, 6, 3)

        # 7 days at hour 10 (wrong hour)
        entries = [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 10, "cost_usd": 99.0}
            for i in range(7)
        ]
        # Only 4 days at hour 14 (right hour, but below threshold)
        entries += [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": 2.0}
            for i in range(4)
        ]

        calc = self._make_calc_with_ledger(entries)
        result = calc.rolling_7d_avg_same_hour("research", target)
        assert result == 0.0, "Records at different hour must not count toward same-hour average"

    def test_7_day_window_excludes_today(self):
        """Window is [target_date - 7, target_date - 1] — target.date() itself excluded."""
        from datetime import datetime, timezone, date, timedelta

        target = datetime(2026, 6, 10, 14, 0, 0, tzinfo=timezone.utc)
        base_date = date(2026, 6, 3)  # 7 days before target_date (June 10)

        # 6 valid days (June 3–8) + 1 day on target date (June 10) = only 6 valid
        entries = [
            {"conv_type": "research", "date": base_date + timedelta(days=i), "hour": 14, "cost_usd": 1.0}
            for i in range(6)  # June 3–8
        ]
        # Add entry ON the target date — must be excluded
        entries.append({"conv_type": "research", "date": date(2026, 6, 10), "hour": 14, "cost_usd": 1.0})

        calc = self._make_calc_with_ledger(entries)
        # 6 valid days only (target date entry excluded) → cold start
        result = calc.rolling_7d_avg_same_hour("research", target)
        assert result == 0.0, "Entry on target_date itself must be excluded from the 7-day window"
