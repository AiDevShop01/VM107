"""
VM102 tools for feature computation (primitives).
"""
from fingpt_core.clients import RetryProfile, VM102Client
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.features.primitives import GetPrimitivesRequest, GetPrimitivesResponse
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool


class ComputePrimitivesTool(ContractTool):
    """
    Compute primitives from VM102.

    Validates against GetPrimitivesRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM102Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetPrimitivesRequest."""
        try:
            return GetPrimitivesRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid primitives request: {e}",
                errors=[str(e)]
            )

    async def _call_vm(self, request: GetPrimitivesRequest) -> dict:
        """Call VM102 compute_primitives endpoint."""
        return await self.client.compute_primitives(
            symbol=request.symbol,
            timeframe=request.timeframe,
            start=request.start,
            end=request.end,
            layer=request.layer
        )

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetPrimitivesResponse."""
        try:
            return GetPrimitivesResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid primitives response: {e}",
                errors=[str(e)]
            )

    def _format_response(self, contract: GetPrimitivesResponse) -> Response:
        """Format primitives response for agent."""
        message = f"Computed {contract.count} feature bars for {contract.symbol} {contract.timeframe}"
        return Response(message=message, break_loop=False)
