"""
AgentRunner cleanup extension.

Transitions to COMPLETE and cleans up when monologue ends.
Uses _85_ prefix to run BEFORE existing _90_waiting_for_input_msg.py.
"""
from helpers.extension import Extension
from helpers.print_style import PrintStyle


class RunnerCleanup(Extension):
    """Clean up AgentRunner when monologue ends."""

    async def execute(self, **kwargs):
        """
        Transition to COMPLETE and clean up runner.

        Handles terminal states:
        - RUNNING: Transition to COMPLETE
        - COMPLETE/FAILED/CANCELLED: Already terminal, just cleanup
        - PAUSED: Transition to COMPLETE (monologue ending means task is done)
        """
        if not self.agent:
            return

        try:
            # Get runner if it exists
            runner = self.agent.get_data("runner")
            if runner is None:
                # No runner to clean up
                return

            # Import here to avoid circular dependencies
            from core.state_machine import AgentState

            current_state = runner.state

            # Transition to COMPLETE if still running/paused
            if current_state == AgentState.RUNNING:
                await runner.complete()
                PrintStyle.debug("AgentRunner transitioned to COMPLETE")
            elif current_state == AgentState.PAUSED:
                # Resume first, then complete
                await runner.resume()
                await runner.complete()
                PrintStyle.debug("AgentRunner resumed and transitioned to COMPLETE")

            # Always cleanup (idempotent)
            await runner.cleanup()
            PrintStyle.debug("AgentRunner cleanup complete")

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"Error in AgentRunner cleanup: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())
