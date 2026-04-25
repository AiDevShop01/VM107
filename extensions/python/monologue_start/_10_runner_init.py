"""
AgentRunner initialization extension.

Creates AgentRunner instance and transitions to RUNNING when monologue starts.
Uses _10_ prefix to run early in monologue_start lifecycle.
"""
from helpers.extension import Extension
from helpers.print_style import PrintStyle


class RunnerInit(Extension):
    """Initialize AgentRunner when monologue starts."""

    async def execute(self, **kwargs):
        """
        Create AgentRunner and transition to RUNNING.

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

            # Create runner with no-op defaults (Phase 36+ will add real implementations)
            runner = AgentRunner(agent=self.agent)

            # Store runner on agent for access by other extensions
            self.agent.set_data("runner", runner)

            # Transition to RUNNING state
            await runner.start()

            PrintStyle.debug("AgentRunner initialized and started")

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            # This ensures backward compatibility - Agent Zero works even if runner fails
            PrintStyle.error(f"Failed to initialize AgentRunner: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())
