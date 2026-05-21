"""
ContractTool base class for Agent Zero VM integration.

Enforces validate-request -> call-VM -> validate-response pipeline.
Errors never crash the agent (break_loop=False always).
"""
import json
import logging
import time
from abc import abstractmethod
from datetime import datetime

from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from helpers.tool import Response, Tool

logger = logging.getLogger("fingpt.tools")


class ContractTool(Tool):
    """
    Base class for all VM contract-based tools.

    Enforces validation pipeline:
    1. Validate request args against Pydantic contract
    2. Call VM via client
    3. Validate response data against Pydantic contract
    4. Format response for agent

    All errors return Response(break_loop=False) - agent never crashes.
    """

    @abstractmethod
    def _validate_request(self, args: dict) -> BaseContract:
        """
        Validate request args against Pydantic contract.

        Args:
            args: Tool arguments from agent

        Returns:
            Validated request contract

        Raises:
            ContractValidationError: If validation fails
        """
        pass

    @abstractmethod
    async def _call_vm(self, request: BaseContract) -> dict:
        """
        Call VM endpoint via client.

        Args:
            request: Validated request contract

        Returns:
            Raw response dict from VM

        Raises:
            Exception: Any VM client error
        """
        pass

    @abstractmethod
    def _validate_response(self, data: dict) -> BaseContract:
        """
        Validate response data against Pydantic contract.

        Args:
            data: Raw response dict from VM

        Returns:
            Validated response contract

        Raises:
            ContractValidationError: If validation fails
        """
        pass

    def _format_response(self, contract: BaseContract) -> Response:
        """
        Format validated response for agent.

        Default implementation returns JSON-formatted contract.
        Subclasses can override for custom formatting.

        Args:
            contract: Validated response contract

        Returns:
            Response object for agent
        """
        message = json.dumps(contract.model_dump(), indent=2, default=str)
        return Response(message=message, break_loop=False)

    async def execute(self, **kwargs) -> Response:
        """
        Execute tool with validation pipeline.

        Pipeline:
        1. Record start time
        2. Validate request
        3. Call VM
        4. Validate response
        5. Log success
        6. Format response

        Error handling:
        - ContractValidationError: Log validation_failed, return error Response
        - Any Exception: Log error, return error Response
        - Never crashes agent (break_loop=False always)

        Returns:
            Response object (never raises)
        """
        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            # BUG-16: LLMs sometimes hallucinate X-Agent-Scope (or other X-* transport-layer
            # headers) into tool_args. Strip them before Pydantic validation so extra="forbid"
            # contracts don't reject the call. Log a WARNING so prompt drift is visible.
            _stripped_keys = [k for k in self.args if k.startswith("X-")]
            if _stripped_keys:
                logging.getLogger("fingpt.tools.vm_contracts").warning(
                    "ContractTool[%s]: stripped transport-layer keys from tool_args: %s (BUG-16 fallback)",
                    type(self).__name__,
                    _stripped_keys,
                )
                self.args = {k: v for k, v in self.args.items() if not k.startswith("X-")}

            # BUG-21a: LLMs sometimes nest X-* headers inside a 'headers' dict in tool_args,
            # e.g. {"trade_id": "abc", "headers": {"X-Agent-Scope": "..."}}.
            # BUG-16's top-level X-* strip does NOT catch this nested form.
            # 'headers' is never a legitimate field for any ContractTool subclass — strip it
            # unconditionally and log the contents so prompt drift is observable.
            if "headers" in self.args:
                _headers_val = self.args["headers"]
                _nested_keys = list(_headers_val.keys()) if isinstance(_headers_val, dict) else []
                logging.getLogger("fingpt.tools.vm_contracts").warning(
                    "ContractTool[%s]: stripped nested 'headers' field from tool_args "
                    "(value=%r, nested_keys=%s) — 'headers' is never a valid tool arg (BUG-21a fallback)",
                    type(self).__name__,
                    _headers_val if not isinstance(_headers_val, dict) else "<dict>",
                    _nested_keys,
                )
                self.args = {k: v for k, v in self.args.items() if k != "headers"}

            # Validate request
            request = self._validate_request(self.args)

            # Call VM
            response_data = await self._call_vm(request)

            # Validate response
            response = self._validate_response(response_data)

            # Log success
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "event": "tool_execution",
                "tool": self.name,
                "status": "success",
                "duration_ms": duration_ms,
                "timestamp": timestamp
            }))

            # Format response
            return self._format_response(response)

        except ContractValidationError as e:
            # Validation failure - log and return error Response
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(json.dumps({
                "event": "tool_execution",
                "tool": self.name,
                "status": "validation_failed",
                "error": str(e),
                "duration_ms": duration_ms,
                "timestamp": timestamp
            }))
            return Response(
                message=f"Contract validation failed: {e}",
                break_loop=False
            )

        except Exception as e:
            # Execution failure - log and return error Response
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(json.dumps({
                "event": "tool_execution",
                "tool": self.name,
                "status": "error",
                "error": str(e),
                "duration_ms": duration_ms,
                "timestamp": timestamp
            }))
            return Response(
                message=f"Tool execution failed: {e}",
                break_loop=False
            )
