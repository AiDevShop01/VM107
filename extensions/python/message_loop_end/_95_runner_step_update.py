"""
AgentRunner step update extension.

Updates execution context after each message loop iteration.
Uses _95_ prefix to run late in message_loop_end (after existing _10_organize_history.py).
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from helpers.extension import Extension
from helpers.print_style import PrintStyle

if TYPE_CHECKING:
    from agent import LoopData


class RunnerStepUpdate(Extension):
    """Update AgentRunner execution context after each step."""

    async def execute(self, loop_data=None, **kwargs):
        """
        Update execution context and run step.

        Args:
            loop_data: Agent Zero loop data (unused but received from Agent Zero)
        """
        if not self.agent:
            return

        try:
            # Get runner if it exists
            runner = self.agent.get_data("runner")
            if runner is None:
                # Graceful degradation: Agent Zero works without runner
                return

            # Run step (increments step_count, checks stall, logs metrics)
            await runner.run_step()

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"Error in AgentRunner step update: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())
