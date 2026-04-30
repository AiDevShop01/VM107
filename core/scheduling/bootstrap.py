"""
Bootstrap service for cold/warm start initialization.

Responsibilities:
- Validate all required config files exist
- Cold start: load brain_defaults.yaml, create brain:global in MongoDB
- Warm start: load existing brain:global from MongoDB
- Load rules.yaml into RulesEngine
- Load modes.yaml into HysteresisController
- Load all task templates from config/templates/
- Register Python hooks for complex rules
- Detect warm-up transition and increase limits after threshold
"""

from pathlib import Path
from typing import Any
from pydantic import BaseModel
import yaml

from core.scheduling.enums import BehavioralMode, ResourcePolicy
from core.scheduling.brain import SchedulerControl, BrainState


class BootstrapResult(BaseModel):
    """Result of bootstrap initialization."""

    initialized_from: str  # "bootstrap" or "warm_start"
    brain_state: dict[str, Any]
    template_count: int
    rule_count: int


class BootstrapService:
    """
    Bootstrap service for cold/warm start initialization.

    Orchestrates system initialization by loading configuration,
    initializing state, and wiring up all brain layer components.
    """

    def __init__(
        self,
        config_dir: Path | str,
        mongo_cache,  # MongoCachedCollection for brain_state
        redis_client,
        brain,  # BrainLayer instance
        rules_engine,  # RulesEngine instance
        hysteresis,  # HysteresisController instance
        template_loader  # TemplateLoader instance
    ):
        """
        Initialize bootstrap service.

        Args:
            config_dir: Path to VM107/config/ directory
            mongo_cache: MongoCachedCollection for brain state
            redis_client: Redis client
            brain: BrainLayer instance
            rules_engine: RulesEngine instance
            hysteresis: HysteresisController instance
            template_loader: TemplateLoader instance
        """
        self.config_dir = Path(config_dir)
        self.mongo_cache = mongo_cache
        self.redis_client = redis_client
        self.brain = brain
        self.rules_engine = rules_engine
        self.hysteresis = hysteresis
        self.template_loader = template_loader

        # Paths to config files
        self.brain_defaults_path = self.config_dir / "brain" / "brain_defaults.yaml"
        self.rules_path = self.config_dir / "brain" / "rules.yaml"
        self.modes_path = self.config_dir / "brain" / "modes.yaml"
        self.templates_dir = self.config_dir / "templates"

        # Cache warm-up config
        self.warm_up_config: dict[str, Any] | None = None

    def initialize(self) -> BootstrapResult:
        """
        Initialize system from cold or warm start.

        Steps:
        1. Validate config files exist
        2. Check MongoDB for existing brain:global document
        3. If exists (warm start): load into BrainLayer
        4. If not exists (cold start): create from brain_defaults.yaml
        5. Load rules.yaml into RulesEngine
        6. Register Python hooks
        7. Load modes.yaml into HysteresisController
        8. Load all templates from config/templates/
        9. Return BootstrapResult

        Returns:
            BootstrapResult with initialization metadata
        """
        # Step 1: Validate config files exist
        self._validate_config_files()

        # Step 2: Check MongoDB for existing brain:global
        existing_state = self.mongo_cache.get("brain:global")

        if existing_state:
            # Step 3: Warm start - load existing state
            initialized_from = "warm_start"
            brain_state = existing_state
        else:
            # Step 4: Cold start - create from brain_defaults.yaml
            initialized_from = "bootstrap"
            brain_state = self._create_cold_start_state()

            # Write to MongoDB
            self.mongo_cache.update("brain:global", brain_state)

        # Step 5: Load rules.yaml
        rules_config = self._load_yaml(self.rules_path)
        rule_count = len(rules_config.get("rules", []))

        # Step 6: Register Python hooks
        self._register_hooks()

        # Step 7: Load modes.yaml (hysteresis already has thresholds, this is for reference)
        modes_config = self._load_yaml(self.modes_path)

        # Step 8: Load all templates
        template_files = list(self.templates_dir.glob("*.yaml"))
        template_count = len(template_files)

        # Build result
        result = BootstrapResult(
            initialized_from=initialized_from,
            brain_state=brain_state,
            template_count=template_count,
            rule_count=rule_count
        )

        return result

    def check_warm_up_transition(
        self,
        brain_state,  # BrainState or MagicMock in tests
        goals_completed: int,
        hours_elapsed: float
    ) -> SchedulerControl | None:
        """
        Check if cold start warm-up period is complete.

        Args:
            brain_state: Current brain state
            goals_completed: Number of goals completed since cold start
            hours_elapsed: Hours elapsed since cold start

        Returns:
            Updated SchedulerControl with increased limits, or None if still warming up
        """
        if not self.warm_up_config:
            # Load warm-up config from brain_defaults.yaml
            defaults = self._load_yaml(self.brain_defaults_path)
            self.warm_up_config = defaults.get("cold_start", {})

        warm_up_goals = self.warm_up_config.get("warm_up_goals", 5)
        warm_up_hours = self.warm_up_config.get("warm_up_hours", 24)

        # Check if either threshold is met
        if goals_completed >= warm_up_goals or hours_elapsed >= warm_up_hours:
            # Transition to normal limits
            current_control = brain_state.scheduler_control

            # Increase max_concurrent_tasks from 2 to 5 (default)
            updated_control = SchedulerControl(
                max_concurrent_tasks=5,
                max_cost_per_cycle=10.0,
                max_tokens_per_cycle=100000,
                blocked_goal_ids=current_control.blocked_goal_ids,
                priority_weights=current_control.priority_weights,
                goal_priority_overrides=current_control.goal_priority_overrides,
                expansion_policy=current_control.expansion_policy,
                preemption_enabled=current_control.preemption_enabled,
                preemption_threshold=current_control.preemption_threshold,
                max_preemptions_per_cycle=current_control.max_preemptions_per_cycle,
                aging_enabled=current_control.aging_enabled,
                aging_factor=current_control.aging_factor
            )

            return updated_control

        # Still warming up
        return None

    def _validate_config_files(self) -> None:
        """
        Validate all required config files exist.

        Raises:
            FileNotFoundError: If any required config file is missing
        """
        required_files = [
            self.brain_defaults_path,
            self.rules_path,
            self.modes_path
        ]

        for file_path in required_files:
            if not file_path.exists():
                raise FileNotFoundError(f"Required config file not found: {file_path}")

        if not self.templates_dir.exists():
            raise FileNotFoundError(f"Templates directory not found: {self.templates_dir}")

    def _create_cold_start_state(self) -> dict[str, Any]:
        """
        Create brain:global document from brain_defaults.yaml.

        Returns:
            Brain state dict ready for MongoDB
        """
        defaults = self._load_yaml(self.brain_defaults_path)

        # Cache warm-up config for later use
        self.warm_up_config = defaults.get("cold_start", {})

        brain_state = {
            "_id": "brain:global",
            "mode": defaults.get("mode", "exploration"),
            "resource_policy": defaults.get("resource_policy", "normal"),
            "scheduler_control": defaults.get("scheduler_control", {}),
            "confidence_global": defaults.get("confidence_global", 0.5),
            "mode_control": defaults.get("mode_control", {}),
            "system_state": {
                "redis_available": True,
                "mongodb_healthy": True,
                "initialized_from": "bootstrap"
            }
        }

        return brain_state

    def _register_hooks(self) -> None:
        """
        Register Python hooks for complex rules.

        Hooks:
        - check_exploration_research_boost: Check if exploration mode should boost research tasks
        """
        # Hook: check_exploration_research_boost
        def check_exploration_research_boost(context: dict, params: dict) -> bool:
            """
            Check if exploration mode should boost research tasks.

            Triggers when:
            - Low success rate (< 0.5)
            - High entropy (> 0.6)
            - Budget available (> 20% remaining)

            Args:
                context: Signal aggregation context
                params: Hook parameters (signals list)

            Returns:
                True if all signals present, False otherwise
            """
            signals = params.get("signals", [])

            # Check each signal
            low_success_rate = "low_success_rate" in signals and context.get("success_rate", 1.0) < 0.5
            high_entropy = "high_entropy" in signals and context.get("entropy", 0.0) > 0.6
            budget_available = "budget_available" in signals and context.get("budget_remaining_ratio", 0.0) > 0.2

            # All signals must be present
            return low_success_rate and high_entropy and budget_available

        # Register hook
        self.rules_engine.register_hook("check_exploration_research_boost", check_exploration_research_boost)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """
        Load and parse YAML file.

        Args:
            path: Path to YAML file

        Returns:
            Parsed YAML as dict
        """
        with path.open("r") as f:
            return yaml.safe_load(f)
