"""
VM109 tools for trading account and instrument config.
"""
from fingpt_core.clients import RetryProfile, VM109Client
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.trading.accounts import GetAccountRequest, GetAccountResponse
from fingpt_core.contracts.trading.instruments import GetInstrumentConfigRequest, GetInstrumentConfigResponse
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool


class GetAccountTool(ContractTool):
    """
    Get account details from VM109.

    Validates against GetAccountRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM109Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetAccountRequest."""
        try:
            return GetAccountRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid account request: {e}",
                errors=[str(e)]
            )

    async def _call_vm(self, request: GetAccountRequest) -> dict:
        """Call VM109 get_account endpoint."""
        return await self.client.get_account(account_id=request.account_id)

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetAccountResponse."""
        try:
            return GetAccountResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid account response: {e}",
                errors=[str(e)]
            )

    def _format_response(self, contract: GetAccountResponse) -> Response:
        """Format account response for agent."""
        message = f"Account {contract.account_id}: Balance {contract.balance:.2f} {contract.currency}"
        return Response(message=message, break_loop=False)


class GetInstrumentConfigTool(ContractTool):
    """
    Get instrument configuration from VM109.

    Validates against GetInstrumentConfigRequest/Response contracts.
    Uses FAST_FAIL retry profile for agent responsiveness.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = VM109Client(profile=RetryProfile.FAST_FAIL)

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetInstrumentConfigRequest."""
        try:
            return GetInstrumentConfigRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid instrument config request: {e}",
                errors=[str(e)]
            )

    async def _call_vm(self, request: GetInstrumentConfigRequest) -> dict:
        """Call VM109 get_instrument_config endpoint."""
        return await self.client.get_instrument_config(symbol=request.symbol)

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetInstrumentConfigResponse."""
        try:
            return GetInstrumentConfigResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                message=f"Invalid instrument config response: {e}",
                errors=[str(e)]
            )

    def _format_response(self, contract: GetInstrumentConfigResponse) -> Response:
        """Format instrument config response for agent."""
        message = f"Instrument {contract.symbol}: {len(contract.timeframes)} timeframes configured"
        return Response(message=message, break_loop=False)
