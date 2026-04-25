"""
5-level config resolution hierarchy for boundary configuration.

Priority (highest to lowest):
1. Runtime override
2. Task/goal constraints (placeholder for Phase 42)
3. Agent-specific config
4. Environment config
5. Default config
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
import yaml


class BoundaryConfig(BaseModel):
    """Boundary configuration for a single level (partial config allowed)."""
    model_config = ConfigDict(extra="forbid")

    max_steps: Optional[int] = None
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    max_execution_time_sec: Optional[int] = None
    daily_budget_usd: Optional[float] = None


class ResolvedBoundaryConfig(BaseModel):
    """Immutable resolved boundary config after merging all levels."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int = Field(ge=1, description="Maximum execution steps per task")
    max_tokens: int = Field(ge=1, description="Maximum total tokens per task")
    max_cost_usd: float = Field(ge=0.0, description="Maximum USD cost per task")
    max_execution_time_sec: int = Field(ge=1, description="Maximum wall-clock seconds")
    daily_budget_usd: float = Field(ge=0.0, description="System-wide daily spend cap")


class ConfigResolver:
    """Resolve boundary config from 5-level hierarchy."""

    def __init__(self, yaml_path: str):
        """
        Initialize config resolver with YAML config file.

        Args:
            yaml_path: Path to boundary.yaml
        """
        with open(yaml_path) as f:
            self._raw_config = yaml.safe_load(f)

    def resolve(
        self,
        agent_name: Optional[str] = None,
        task_id: Optional[str] = None,
        environment: Optional[str] = "production",
        runtime_override: Optional[BoundaryConfig] = None
    ) -> ResolvedBoundaryConfig:
        """
        Resolve config from 5 levels (highest priority wins).

        Args:
            agent_name: Agent name for agent-specific config
            task_id: Task ID for task-level constraints (future)
            environment: Environment name (research/staging/production, None = default only)
            runtime_override: Runtime override config (highest priority)

        Returns:
            Immutable ResolvedBoundaryConfig

        Priority:
          1. Runtime override (highest)
          2. Task/goal constraints (placeholder for Phase 42)
          3. Agent-specific config
          4. Environment config
          5. Default config (lowest)
        """
        # Level 5: Default config
        merged = self._raw_config["default"].copy()

        # Level 4: Environment config
        if environment and environment in self._raw_config.get("environments", {}):
            env_config = self._raw_config["environments"][environment]
            merged.update({k: v for k, v in env_config.items() if v is not None})

        # Level 3: Agent-specific config
        if agent_name and agent_name in self._raw_config.get("agents", {}):
            agent_config = self._raw_config["agents"][agent_name]
            merged.update({k: v for k, v in agent_config.items() if v is not None})

        # Level 2: Task/goal constraints
        # TODO: Phase 42 integration with task ledger
        # if task_id:
        #     task_config = task_ledger.get_task_config(task_id)
        #     merged.update({k: v for k, v in task_config.items() if v is not None})

        # Level 1: Runtime override (highest priority)
        if runtime_override:
            runtime_dict = runtime_override.model_dump(exclude_unset=True)
            merged.update({k: v for k, v in runtime_dict.items() if v is not None})

        return ResolvedBoundaryConfig(**merged)
