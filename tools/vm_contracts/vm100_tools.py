"""
VM100 tools for journal and trade data.
"""
from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.journal.entries import CreatePreTradeEntryRequest, CreatePreTradeEntryResponse
from fingpt_core.contracts.trading.trades import GetRecentTradesRequest, GetRecentTradesResponse
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool


class GetRecentTradesTool(ContractTool):
    """
    Get recent trades from VM100.

    Validates against GetRecentTradesRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM100Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetRecentTradesRequest."""
        try:
            return GetRecentTradesRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid recent trades request: {e}",
                errors=[str(e)]
            )

    async def _call_vm(self, request: GetRecentTradesRequest) -> dict:
        """Call VM100 get_recent_trades endpoint."""
        return await self.client.get_recent_trades(
            account_id=request.account_id,
            limit=request.limit,
            symbol=request.symbol
        )

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetRecentTradesResponse."""
        try:
            return GetRecentTradesResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid recent trades response: {e}",
                errors=[str(e)]
            )

    def _format_response(self, contract: GetRecentTradesResponse) -> Response:
        """Format recent trades response for agent."""
        message = f"Retrieved {contract.count} trades"
        return Response(message=message, break_loop=False)


class CreatePreTradeEntryTool(ContractTool):
    """
    Create pre-trade journal entry in VM100.

    Validates against CreatePreTradeEntryRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM100Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against CreatePreTradeEntryRequest."""
        try:
            return CreatePreTradeEntryRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid create pre-trade entry request: {e}",
                errors=[str(e)]
            )

    async def _call_vm(self, request: CreatePreTradeEntryRequest) -> dict:
        """Call VM100 create_pre_trade_entry endpoint."""
        return await self.client.create_pre_trade_entry(
            symbol=request.symbol,
            timeframe=request.timeframe,
            analysis=request.analysis
        )

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against CreatePreTradeEntryResponse."""
        try:
            return CreatePreTradeEntryResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid create pre-trade entry response: {e}",
                errors=[str(e)]
            )

    def _format_response(self, contract: CreatePreTradeEntryResponse) -> Response:
        """Format create pre-trade entry response for agent."""
        message = f"Created pre-trade entry {contract.entry_id} for {contract.symbol} {contract.timeframe}"
        return Response(message=message, break_loop=False)
