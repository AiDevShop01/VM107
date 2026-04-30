"""
Tests for Bootstrap service.

Validates:
- Cold start initialization from brain_defaults.yaml
- Warm start from existing MongoDB state
- Config file validation
- Warm-up transition logic
- Template loading
- Rules engine initialization
- Hysteresis controller initialization
"""

from pathlib import Path
from unittest.mock import Mock, MagicMock
import pytest
import yaml

from core.scheduling.bootstrap import BootstrapService, BootstrapResult
from core.scheduling.enums import BehavioralMode, ResourcePolicy


class TestBootstrapService:
    """Test bootstrap service initialization."""

    @pytest.fixture
    def mock_mongo_cache(self):
        """Mock MongoDB cached collection."""
        return Mock()

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        return Mock()

    @pytest.fixture
    def mock_brain(self):
        """Mock Brain layer."""
        brain = Mock()
        brain.get_state = Mock()
        return brain

    @pytest.fixture
    def mock_rules_engine(self):
        """Mock rules engine."""
        engine = Mock()
        engine.register_hook = Mock()
        return engine

    @pytest.fixture
    def mock_hysteresis(self):
        """Mock hysteresis controller."""
        return Mock()

    @pytest.fixture
    def mock_template_loader(self):
        """Mock template loader."""
        loader = Mock()
        loader.load = Mock()
        return loader

    @pytest.fixture
    def config_dir(self, tmp_path):
        """Create temporary config directory with YAML files."""
        config_dir = tmp_path / "config"
        brain_dir = config_dir / "brain"
        templates_dir = config_dir / "templates"

        brain_dir.mkdir(parents=True)
        templates_dir.mkdir(parents=True)

        # Create brain_defaults.yaml
        brain_defaults = {
            "version": 1,
            "mode": "exploration",
            "resource_policy": "normal",
            "scheduler_control": {
                "max_concurrent_tasks": 2,
                "max_cost_per_cycle": 5.0,
                "max_tokens_per_cycle": 50000,
                "priority_weights": {"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
                "goal_priority_overrides": {},
                "blocked_goal_ids": [],
                "expansion_policy": "enabled",
                "preemption_enabled": False,
                "preemption_threshold": 2.0,
                "max_preemptions_per_cycle": 1,
                "aging_enabled": True,
                "aging_factor": 1.0
            },
            "confidence_global": 0.5,
            "mode_control": {
                "min_hold_seconds": 60,
                "confirmation_cycles": 3
            },
            "cold_start": {
                "warm_up_goals": 5,
                "warm_up_hours": 24
            }
        }

        with (brain_dir / "brain_defaults.yaml").open("w") as f:
            yaml.dump(brain_defaults, f)

        # Create rules.yaml
        rules = {
            "version": 1,
            "rules": [
                {
                    "name": "switch_to_stabilization",
                    "priority": 1,
                    "condition": {"field": "failure_rate", "op": ">", "value": 0.3},
                    "action": {"type": "set_mode", "params": {"mode": "stabilization"}},
                    "cooldown_seconds": 300
                }
            ]
        }

        with (brain_dir / "rules.yaml").open("w") as f:
            yaml.dump(rules, f)

        # Create modes.yaml
        modes = {
            "version": 1,
            "confirmation_cycles": 3,
            "min_hold_seconds": 60,
            "modes": {
                "exploration": {
                    "enter_threshold": 0.6,
                    "exit_threshold": 0.4,
                    "primary_signal": "entropy",
                    "task_type_weights": {"research": 1.3, "execution": 0.8}
                }
            }
        }

        with (brain_dir / "modes.yaml").open("w") as f:
            yaml.dump(modes, f)

        # Create template files
        for template_name in ["research_v1", "maintenance_v1", "learning_v1", "execution_v1", "system_v1"]:
            template = {
                "template_id": template_name,
                "goal_type": template_name.replace("_v1", ""),
                "version": 1,
                "tasks": []
            }
            with (templates_dir / f"{template_name}.yaml").open("w") as f:
                yaml.dump(template, f)

        return config_dir

    def test_cold_start_initialization(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test cold start when MongoDB has no brain:global document."""
        # MongoDB has no existing brain:global
        mock_mongo_cache.get.return_value = None

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        result = bootstrap.initialize()

        # Should have created brain:global in MongoDB
        mock_mongo_cache.update.assert_called_once()
        call_args = mock_mongo_cache.update.call_args
        assert call_args[0][0] == "brain:global"

        # Should indicate cold start
        assert result.initialized_from == "bootstrap"

        # Should have loaded templates
        assert result.template_count == 5

        # Should have loaded rules
        assert result.rule_count == 1

    def test_warm_start_initialization(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test warm start when brain:global exists in MongoDB."""
        # MongoDB has existing brain:global
        existing_state = {
            "_id": "brain:global",
            "mode": "exploitation",
            "resource_policy": "constrained",
            "confidence_global": 0.8
        }
        mock_mongo_cache.get.return_value = existing_state

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        result = bootstrap.initialize()

        # Should NOT create brain:global (already exists)
        mock_mongo_cache.update.assert_not_called()

        # Should indicate warm start
        assert result.initialized_from == "warm_start"

        # Should still load templates and rules
        assert result.template_count == 5
        assert result.rule_count == 1

    def test_missing_config_file_raises_error(
        self,
        tmp_path,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test that missing config files raise clear error."""
        # Config directory with missing files
        empty_config_dir = tmp_path / "empty_config"
        empty_config_dir.mkdir()

        bootstrap = BootstrapService(
            config_dir=empty_config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        with pytest.raises(FileNotFoundError) as exc_info:
            bootstrap.initialize()

        assert "brain_defaults.yaml" in str(exc_info.value)

    def test_warm_up_transition_after_goals_threshold(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test warm-up transition increases limits after goals threshold."""
        from core.scheduling.brain import SchedulerControl

        mock_mongo_cache.get.return_value = None

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        # Cold start defaults to 2 workers
        # After 5 goals, should transition to normal limits
        brain_state = MagicMock()
        brain_state.scheduler_control = SchedulerControl(
            max_concurrent_tasks=2,
            max_cost_per_cycle=5.0,
            max_tokens_per_cycle=50000,
            blocked_goal_ids=[],
            priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
            goal_priority_overrides={},
            expansion_policy="enabled",
            preemption_enabled=False,
            preemption_threshold=2.0,
            max_preemptions_per_cycle=1,
            aging_enabled=True,
            aging_factor=1.0
        )

        updated_control = bootstrap.check_warm_up_transition(
            brain_state=brain_state,
            goals_completed=5,
            hours_elapsed=2
        )

        # Should increase max_concurrent_tasks from 2 to 5 (default)
        assert updated_control is not None
        assert updated_control.max_concurrent_tasks > 2

    def test_warm_up_transition_after_hours_threshold(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test warm-up transition increases limits after hours threshold."""
        from core.scheduling.brain import SchedulerControl

        mock_mongo_cache.get.return_value = None

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        # After 24 hours, should transition to normal limits
        brain_state = MagicMock()
        brain_state.scheduler_control = SchedulerControl(
            max_concurrent_tasks=2,
            max_cost_per_cycle=5.0,
            max_tokens_per_cycle=50000,
            blocked_goal_ids=[],
            priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
            goal_priority_overrides={},
            expansion_policy="enabled",
            preemption_enabled=False,
            preemption_threshold=2.0,
            max_preemptions_per_cycle=1,
            aging_enabled=True,
            aging_factor=1.0
        )

        updated_control = bootstrap.check_warm_up_transition(
            brain_state=brain_state,
            goals_completed=2,
            hours_elapsed=24
        )

        # Should increase max_concurrent_tasks
        assert updated_control is not None
        assert updated_control.max_concurrent_tasks > 2

    def test_warm_up_no_transition_before_threshold(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test warm-up does NOT transition before thresholds."""
        from core.scheduling.brain import SchedulerControl

        mock_mongo_cache.get.return_value = None

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        brain_state = MagicMock()
        brain_state.scheduler_control = SchedulerControl(
            max_concurrent_tasks=2,
            max_cost_per_cycle=5.0,
            max_tokens_per_cycle=50000,
            blocked_goal_ids=[],
            priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
            goal_priority_overrides={},
            expansion_policy="enabled",
            preemption_enabled=False,
            preemption_threshold=2.0,
            max_preemptions_per_cycle=1,
            aging_enabled=True,
            aging_factor=1.0
        )

        # Not enough goals and not enough time
        updated_control = bootstrap.check_warm_up_transition(
            brain_state=brain_state,
            goals_completed=3,
            hours_elapsed=12
        )

        # Should NOT transition yet
        assert updated_control is None

    def test_python_hooks_registered(
        self,
        config_dir,
        mock_mongo_cache,
        mock_redis,
        mock_brain,
        mock_rules_engine,
        mock_hysteresis,
        mock_template_loader
    ):
        """Test that Python hooks are registered during initialization."""
        mock_mongo_cache.get.return_value = None

        bootstrap = BootstrapService(
            config_dir=config_dir,
            mongo_cache=mock_mongo_cache,
            redis_client=mock_redis,
            brain=mock_brain,
            rules_engine=mock_rules_engine,
            hysteresis=mock_hysteresis,
            template_loader=mock_template_loader
        )

        bootstrap.initialize()

        # Should have registered check_exploration_research_boost hook
        mock_rules_engine.register_hook.assert_called()
        call_args_list = [call[0][0] for call in mock_rules_engine.register_hook.call_args_list]
        assert "check_exploration_research_boost" in call_args_list
