"""
ValidationExtension for contract enforcement.

Validates agent outputs against schema registry when _contract_type is present.
Uses _90_ prefix to run after _10_organize_history.py but before _95_runner_step_update.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from core.contracts.validator import format_validation_error, validate_agent_output
from core.state_machine import AgentState
from helpers.extension import Extension
from helpers.print_style import PrintStyle

if TYPE_CHECKING:
    from agent import LoopData


logger = logging.getLogger("agentrunner")


class ValidationExtension(Extension):
    """Validate agent outputs against contract schemas."""

    async def execute(self, loop_data=None, **kwargs):
        """
        Validate agent output if _contract_type is present.

        Gracefully skips validation if:
        - No runner exists (agent running without AgentRunner)
        - Runner not in RUNNING state (paused/complete/etc)
        - Response has no _contract_type key (most message loops)

        On validation failure:
        - Logs structured JSON with error details
        - Calls runner.fail() to transition to FAILED state

        Args:
            loop_data: Agent Zero loop data (may contain response)
            **kwargs: Additional keyword arguments from Agent Zero
        """
        if not self.agent:
            return

        try:
            # Get runner if it exists
            runner = self.agent.get_data("runner")
            if runner is None:
                # Graceful skip: Agent Zero works without runner
                return

            # Skip validation if not running
            if runner.state != AgentState.RUNNING:
                # No validation needed for paused/complete/failed states
                return

            # Get response from loop_data or kwargs
            response = self._extract_response(loop_data, kwargs)
            if response is None:
                # No response data - most message loops won't have validated output
                return

            # Check if this response needs contract validation
            if not isinstance(response, dict):
                return

            contract_type = response.get("_contract_type")
            if contract_type is None:
                # No contract type specified - skip validation (expected for most responses)
                return

            # Extract contract data (defaults to full response if not specified)
            contract_data = response.get("_contract_data", response)

            # Validate against schema registry
            validated = validate_agent_output(contract_type, contract_data)

            # Log success
            self._log_validation_success(contract_type)

        except ValidationError as e:
            # Validation failed - log error and fail the step
            self._log_validation_failure(contract_type, e)

            # Fail the runner step (transition to FAILED state)
            error_summary = self._get_error_summary(e)
            await runner.fail(f"Contract validation failed: {error_summary}")

        except ValueError as e:
            # Unknown contract type - log error and fail
            self._log_unknown_contract_type(str(e))
            await runner.fail(f"Unknown contract type: {e}")

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"Error in ValidationExtension: {e}")
            import traceback
            PrintStyle.debug(traceback.format_exc())

    def _extract_response(self, loop_data, kwargs) -> dict[str, Any] | None:
        """
        Extract response data from loop_data or kwargs.

        Args:
            loop_data: Agent Zero loop data
            kwargs: Additional keyword arguments

        Returns:
            Response dict or None if not found
        """
        # Try loop_data first
        if loop_data is not None:
            if hasattr(loop_data, "response"):
                return loop_data.response
            if isinstance(loop_data, dict) and "response" in loop_data:
                return loop_data["response"]

        # Try kwargs
        if "response" in kwargs:
            return kwargs["response"]

        return None

    def _log_validation_success(self, schema: str) -> None:
        """
        Log successful validation as structured JSON.

        Args:
            schema: Schema type that was validated
        """
        log_data = {
            "event": "validation_success",
            "agent": self.agent.agent_name if self.agent else "unknown",
            "schema": schema,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        logger.info(json.dumps(log_data))

    def _log_validation_failure(self, schema: str, error: ValidationError) -> None:
        """
        Log validation failure as structured JSON.

        Args:
            schema: Schema type that failed validation
            error: Pydantic ValidationError with field-level details
        """
        error_details = format_validation_error(error)

        log_data = {
            "event": "validation_failed",
            "agent": self.agent.agent_name if self.agent else "unknown",
            "schema": schema,
            "error_details": error_details,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        logger.error(json.dumps(log_data))

    def _log_unknown_contract_type(self, error_msg: str) -> None:
        """
        Log unknown contract type error as structured JSON.

        Args:
            error_msg: Error message from ValueError
        """
        log_data = {
            "event": "unknown_contract_type",
            "agent": self.agent.agent_name if self.agent else "unknown",
            "error": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        logger.error(json.dumps(log_data))

    def _get_error_summary(self, error: ValidationError) -> str:
        """
        Get brief error summary for fail message.

        Args:
            error: Pydantic ValidationError

        Returns:
            Brief summary string (e.g., "3 validation errors")
        """
        error_count = len(error.errors())
        return f"{error_count} validation error{'s' if error_count != 1 else ''}"
