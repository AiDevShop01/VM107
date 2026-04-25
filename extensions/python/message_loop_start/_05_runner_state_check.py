"""
AgentRunner state check extension.

Checks runner state before each message loop iteration and updates execution context.
Uses _05_ prefix to run BEFORE existing _10_iteration_no.py.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from helpers.extension import Extension
from helpers.print_style import PrintStyle

if TYPE_CHECKING:
    from agent import LoopData


class RunnerStateCheck(Extension):
    """Check AgentRunner state before each loop iteration."""

    async def execute(self, loop_data=None, **kwargs):
        """
        Check runner state and update execution context.

        State handling:
        - RUNNING: Update context and check boundaries
        - PAUSED: Log and return (Agent Zero's handle_intervention will pause)
        - CANCELLED/FAILED: Log and return (monologue will end naturally)
        - No runner: Graceful degradation (Agent Zero works without runner)

        Args:
            loop_data: Agent Zero loop data with iteration count
        """
        if not self.agent:
            return

        try:
            # Get runner if it exists
            runner = self.agent.get_data("runner")
            if runner is None:
                # Graceful degradation: Agent Zero works without runner
                return

            # Import here to avoid circular dependencies
            from core.state_machine import AgentState
            from core.execution_context import BoundaryStatus

            # Check current state
            current_state = runner.state

            if current_state == AgentState.PAUSED:
                PrintStyle.debug("AgentRunner is PAUSED, waiting for resume")
                return

            if current_state in (AgentState.CANCELLED, AgentState.FAILED):
                PrintStyle.debug(f"AgentRunner is {current_state.value}, monologue will end")
                return

            if current_state == AgentState.RUNNING:
                # Update execution context with current iteration
                if loop_data and hasattr(loop_data, "iteration"):
                    runner.execution_context.loop_iterations = loop_data.iteration

                # Check execution boundary
                boundary_status = await runner.boundary.check(runner.execution_context)
                if boundary_status == BoundaryStatus.EXCEEDED:
                    PrintStyle.warning("Execution boundary exceeded, transitioning to FAILED")
                    await runner.fail("boundary_exceeded")
                    return

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"Error in AgentRunner state check: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())
