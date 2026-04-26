"""
VM101 tools for market data (OHLC and instruments).
"""
from fingpt_core.clients import RetryProfile, VM101Client
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.market.ohlc import GetOHLCRequest, GetOHLCResponse
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool


class GetOHLCTool(ContractTool):
    """
    Get OHLC bars from VM101.

    Validates against GetOHLCRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM101Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetOHLCRequest."""
        try:
            return GetOHLCRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid OHLC request: {e}"
            )

    async def _call_vm(self, request: GetOHLCRequest) -> dict:
        """Call VM101 get_ohlc endpoint."""
        return await self.client.get_ohlc(
            symbol=request.symbol,
            timeframe=request.timeframe,
            start=request.start,
            end=request.end,
            limit=request.limit
        )

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetOHLCResponse."""
        try:
            return GetOHLCResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid OHLC response: {e}"
            )

    def _format_response(self, contract: GetOHLCResponse) -> Response:
        """Format OHLC response for agent."""
        message = f"Retrieved {contract.count} bars for {contract.symbol} {contract.timeframe}"
        return Response(message=message, break_loop=False)


class GetInstrumentsTool(ContractTool):
    """
    Get instruments list from VM109.

    Note: Instruments come from VM109, not VM101.
    Validates against GetInstrumentsRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Import VM109Client here to avoid circular dependency
        from fingpt_core.clients import VM109Client
        self.client = VM109Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetInstrumentsRequest."""
        from fingpt_core.contracts.market.instruments import GetInstrumentsRequest
        try:
            return GetInstrumentsRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid instruments request: {e}"
            )

    async def _call_vm(self, request) -> dict:
        """Call VM109 get_instruments endpoint."""
        return await self.client.get_instruments(
            asset_class=request.asset_class,
            enabled_only=request.enabled_only
        )

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetInstrumentsResponse."""
        from fingpt_core.contracts.market.instruments import GetInstrumentsResponse
        try:
            return GetInstrumentsResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid instruments response: {e}"
            )

    def _format_response(self, contract) -> Response:
        """Format instruments response for agent."""
        message = f"Retrieved {contract.count} instruments"
        return Response(message=message, break_loop=False)
