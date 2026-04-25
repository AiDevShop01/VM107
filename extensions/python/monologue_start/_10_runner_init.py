"""
AgentRunner initialization extension.

Creates AgentRunner instance with ExecutionBoundary (if config exists)
and transitions to RUNNING when monologue starts.
Uses _10_ prefix to run early in monologue_start lifecycle.
"""
import os
from helpers.extension import Extension
from helpers.print_style import PrintStyle


class RunnerInit(Extension):
    """Initialize AgentRunner when monologue starts."""

    async def execute(self, **kwargs):
        """
        Create AgentRunner with real or no-op boundary.

        Attempts to load config/boundary.yaml for real enforcement.
        Falls back to NoOpBoundary if config missing or invalid.

        Gracefully handles:
        - Missing agent (no-op)
        - Runner already initialized (reuse)
        - Runner initialization errors (log and continue)
        """
        if not self.agent:
            return

        try:
            # Check if runner already exists (avoid double-initialization)
            runner = self.agent.get_data("runner")
            if runner is not None:
                PrintStyle.debug("AgentRunner already initialized, reusing existing instance")
                return

            # Import here to avoid circular dependencies
            from core.agent_runner import AgentRunner

            # Try to create real ExecutionBoundary
            boundary = self._create_boundary()

            # Create runner with boundary (real or no-op)
            runner = AgentRunner(agent=self.agent, boundary=boundary)

            # Store runner on agent for access by other extensions
            self.agent.set_data("runner", runner)

            # Also store budget tracker for token capture extension
            budget_tracker = self.agent.get_data("boundary_budget_tracker")
            if budget_tracker is None and hasattr(self, "_budget_tracker"):
                self.agent.set_data("boundary_budget_tracker", self._budget_tracker)

            # Transition to RUNNING state
            await runner.start()

            boundary_type = type(boundary).__name__
            PrintStyle.debug(f"AgentRunner initialized with {boundary_type}")

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"Failed to initialize AgentRunner: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())

    def _create_boundary(self):
        """
        Create ExecutionBoundary from config, or fall back to NoOpBoundary.

        Returns NoOpBoundary if:
        - config/boundary.yaml doesn't exist
        - config/boundary.yaml fails to parse
        - Any import or initialization error
        """
        try:
            # Resolve config path
            # In Docker: /a0/config/boundary.yaml
            # In dev: relative to VM107 root
            vm107_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )))
            config_path = os.path.join(vm107_root, "config", "boundary.yaml")

            if not os.path.exists(config_path):
                config_path = "/a0/config/boundary.yaml"

            if not os.path.exists(config_path):
                PrintStyle.debug("No boundary config found, using NoOpBoundary")
                from core.interfaces.boundary import NoOpBoundary
                return NoOpBoundary()

            # Load and resolve config
            from core.boundary.config_resolver import ConfigResolver
            from core.boundary.execution_boundary import ExecutionBoundary

            # Determine agent name and environment
            agent_name = getattr(self.agent, "agent_name", "unknown")
            environment = os.environ.get("A0_ENVIRONMENT", "production")

            resolver = ConfigResolver(config_path)
            config = resolver.resolve(
                agent_name=agent_name,
                environment=environment,
            )

            # Create budget tracker
            # Try MongoDB first, fall back to InMemory
            budget_tracker = self._create_budget_tracker()
            self._budget_tracker = budget_tracker

            # Create real boundary
            boundary = ExecutionBoundary(
                config=config,
                budget_tracker=budget_tracker,
                agent_name=agent_name,
            )

            PrintStyle.debug(
                f"ExecutionBoundary created: max_steps={config.max_steps}, "
                f"max_tokens={config.max_tokens}, max_cost=${config.max_cost_usd}"
            )
            return boundary

        except Exception as e:
            PrintStyle.error(f"Failed to create ExecutionBoundary: {e}, using NoOpBoundary")
            from core.interfaces.boundary import NoOpBoundary
            return NoOpBoundary()

    def _create_budget_tracker(self):
        """Create budget tracker: MongoDB if available, InMemory as fallback."""
        try:
            mongo_uri = os.environ.get("MONGODB_URI")
            if mongo_uri:
                from core.boundary.budget_tracker import MongoBudgetTracker
                return MongoBudgetTracker(mongo_uri)
        except Exception:
            pass

        # Fallback to in-memory
        from core.boundary.budget_tracker import InMemoryBudgetTracker
        return InMemoryBudgetTracker()
