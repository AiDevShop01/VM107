"""
Tests for ConfigResolver 5-level config hierarchy.

Tests YAML config loading, merging, and immutability.
"""
import pytest
from pathlib import Path
from pydantic import ValidationError
from core.boundary.config_resolver import (
    BoundaryConfig,
    ResolvedBoundaryConfig,
    ConfigResolver
)


class TestConfigResolver:
    """Test suite for ConfigResolver."""

    @pytest.fixture
    def boundary_yaml_path(self):
        """Path to boundary.yaml."""
        vm107_root = Path(__file__).parent.parent.parent
        return str(vm107_root / "config" / "boundary.yaml")

    @pytest.fixture
    def test_yaml_path(self, tmp_path):
        """Create a test YAML config."""
        yaml_content = """
version: "1.0"
default:
  max_steps: 100
  max_tokens: 500000
  max_cost_usd: 1.00
  max_execution_time_sec: 3600
  daily_budget_usd: 10.00
environments:
  research:
    max_steps: 500
    max_cost_usd: 5.00
agents:
  test_agent:
    max_steps: 200
    max_tokens: 1000000
"""
        yaml_file = tmp_path / "test_boundary.yaml"
        yaml_file.write_text(yaml_content)
        return str(yaml_file)

    def test_default_config_loads(self, boundary_yaml_path):
        """Default config values resolve when no overrides."""
        resolver = ConfigResolver(boundary_yaml_path)
        config = resolver.resolve(environment=None)

        # Should use default values
        assert config.max_steps == 100
        assert config.max_tokens == 500000
        assert config.max_cost_usd == 1.00
        assert config.max_execution_time_sec == 3600
        assert config.daily_budget_usd == 10.00

    def test_environment_override(self, boundary_yaml_path):
        """Environment config overrides default values."""
        resolver = ConfigResolver(boundary_yaml_path)
        config = resolver.resolve(environment="research")

        # Research environment overrides
        assert config.max_steps == 500
        assert config.max_tokens == 2000000
        assert config.max_cost_usd == 5.00
        assert config.max_execution_time_sec == 7200
        assert config.daily_budget_usd == 50.00

    def test_agent_override(self, boundary_yaml_path):
        """Agent-specific config overrides environment and default."""
        resolver = ConfigResolver(boundary_yaml_path)
        config = resolver.resolve(agent_name="backtester_agent", environment="production")

        # Agent overrides should take priority
        assert config.max_steps == 300  # From agent config
        assert config.max_tokens == 1500000  # From agent config
        assert config.max_cost_usd == 3.00  # From agent config
        assert config.max_execution_time_sec == 7200  # From agent config
        # daily_budget_usd not in agent config, so use environment (production)
        assert config.daily_budget_usd == 10.00

    def test_runtime_override(self, test_yaml_path):
        """Runtime override trumps all other levels."""
        resolver = ConfigResolver(test_yaml_path)

        runtime = BoundaryConfig(max_steps=999, max_cost_usd=99.99)
        config = resolver.resolve(
            agent_name="test_agent",
            environment="research",
            runtime_override=runtime
        )

        # Runtime overrides should win
        assert config.max_steps == 999
        assert config.max_cost_usd == 99.99

        # Non-overridden values should come from lower levels
        assert config.max_tokens == 1000000  # From agent config

    def test_none_values_ignored(self, test_yaml_path):
        """None values in higher-priority levels don't erase lower-priority values."""
        resolver = ConfigResolver(test_yaml_path)

        # Runtime override with None values
        runtime = BoundaryConfig(max_steps=999, max_cost_usd=None)
        config = resolver.resolve(runtime_override=runtime)

        # max_steps should be overridden
        assert config.max_steps == 999

        # max_cost_usd should NOT be erased (use default)
        assert config.max_cost_usd == 1.00

    def test_resolved_config_immutable(self, boundary_yaml_path):
        """ResolvedBoundaryConfig raises on attribute mutation."""
        resolver = ConfigResolver(boundary_yaml_path)
        config = resolver.resolve()

        # Should raise ValidationError on mutation attempt
        with pytest.raises(ValidationError):
            config.max_steps = 999

    def test_resolved_config_validates(self, tmp_path):
        """Invalid values (negative max_steps) raise ValidationError."""
        yaml_content = """
version: "1.0"
default:
  max_steps: -100
  max_tokens: 500000
  max_cost_usd: 1.00
  max_execution_time_sec: 3600
  daily_budget_usd: 10.00
"""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text(yaml_content)

        resolver = ConfigResolver(str(yaml_file))

        # Should raise ValidationError for negative max_steps
        with pytest.raises(ValidationError):
            resolver.resolve()

    def test_full_hierarchy(self, test_yaml_path):
        """All 5 levels merge correctly with priority ordering."""
        resolver = ConfigResolver(test_yaml_path)

        runtime = BoundaryConfig(max_steps=1000)
        config = resolver.resolve(
            agent_name="test_agent",
            environment="research",
            runtime_override=runtime
        )

        # Level 1 (runtime) - highest priority
        assert config.max_steps == 1000

        # Level 3 (agent) - overrides environment and default
        assert config.max_tokens == 1000000

        # Level 4 (environment) - overrides default
        assert config.max_cost_usd == 5.00

        # Level 5 (default) - lowest priority, used when no overrides
        assert config.max_execution_time_sec == 3600
        assert config.daily_budget_usd == 10.00
