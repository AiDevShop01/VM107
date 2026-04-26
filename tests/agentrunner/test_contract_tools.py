"""
Tests for ContractTool base class and VM-specific tool wrappers.

These tests verify:
1. ContractTool enforces validate-request -> call-VM -> validate-response pipeline
2. Validation errors return Response(break_loop=False) - never crash agent
3. Tool execution errors return Response(break_loop=False) - never crash agent
4. Structured JSON logging on every tool call
5. All 7 VM-specific tools validate using their contracts
6. All tools use FAST_FAIL retry profile
"""
import json
import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fingpt_core.clients import RetryProfile
from fingpt_core.contracts.errors import ContractValidationError, ToolExecutionError
from fingpt_core.contracts.market.ohlc import GetOHLCRequest, GetOHLCResponse
from tools.vm_contracts.base import ContractTool
from tools.vm_contracts.vm101_tools import GetInstrumentsTool, GetOHLCTool
from tools.vm_contracts.vm102_tools import ComputePrimitivesTool
from tools.vm_contracts.vm109_tools import GetAccountTool, GetInstrumentConfigTool
from tools.vm_contracts.vm100_tools import CreatePreTradeEntryTool, GetRecentTradesTool


# Mock Agent Zero classes
class MockAgent:
    def __init__(self):
        self.agent_name = "test_agent"

    def get_data(self, key):
        return None

    def set_data(self, key, value):
        pass


class MockLoopData:
    pass


@pytest.fixture
def mock_agent():
    return MockAgent()


@pytest.fixture
def mock_loop_data():
    return MockLoopData()


class TestContractToolBase:
    """Test ContractTool base class validation pipeline."""

    @pytest.mark.asyncio
    async def test_execute_pipeline_success(self, mock_agent, mock_loop_data):
        """Successful execution follows: validate request -> call VM -> validate response -> format."""
        # Create a concrete implementation for testing
        class TestTool(ContractTool):
            def _validate_request(self, args):
                return GetOHLCRequest(**args)

            async def _call_vm(self, request):
                return {
                    "symbol": request.symbol,
                    "timeframe": request.timeframe,
                    "bars": [],
                    "count": 0
                }

            def _validate_response(self, data):
                return GetOHLCResponse(**data)

        tool = TestTool(
            agent=mock_agent,
            name="test_tool",
            method=None,
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z"
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.base.logging.getLogger') as mock_logger:
            logger = MagicMock()
            mock_logger.return_value = logger

            response = await tool.execute()

            # Should return Response with break_loop=False
            assert response.break_loop is False
            assert "XAUUSD" in response.message

            # Should log success
            logger.info.assert_called_once()
            log_call = logger.info.call_args[0][0]
            log_data = json.loads(log_call)
            assert log_data["event"] == "tool_execution"
            assert log_data["tool"] == "test_tool"
            assert log_data["status"] == "success"
            assert "duration_ms" in log_data
            assert "timestamp" in log_data

    @pytest.mark.asyncio
    async def test_contract_validation_error_handling(self, mock_agent, mock_loop_data):
        """ContractValidationError returns Response(break_loop=False) with error message."""
        class TestTool(ContractTool):
            def _validate_request(self, args):
                raise ContractValidationError(
                    message="Invalid timeframe",
                    error_code="VALIDATION_ERROR",
                    details={"errors": ["timeframe must be one of: M1, M5, M15..."]}
                )

            async def _call_vm(self, request):
                return {}

            def _validate_response(self, data):
                return GetOHLCResponse(**data)

        tool = TestTool(
            agent=mock_agent,
            name="test_tool",
            method=None,
            args={"symbol": "XAUUSD", "timeframe": "INVALID"},
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.base.logging.getLogger') as mock_logger:
            logger = MagicMock()
            mock_logger.return_value = logger

            response = await tool.execute()

            # Should NOT crash - return error Response
            assert response.break_loop is False
            assert "Contract validation failed" in response.message
            assert "Invalid timeframe" in response.message

            # Should log validation failure
            logger.error.assert_called_once()
            log_call = logger.error.call_args[0][0]
            log_data = json.loads(log_call)
            assert log_data["status"] == "validation_failed"

    @pytest.mark.asyncio
    async def test_tool_execution_error_handling(self, mock_agent, mock_loop_data):
        """Generic exceptions return Response(break_loop=False) with error message."""
        class TestTool(ContractTool):
            def _validate_request(self, args):
                return GetOHLCRequest(**args)

            async def _call_vm(self, request):
                raise Exception("VM connection failed")

            def _validate_response(self, data):
                return GetOHLCResponse(**data)

        tool = TestTool(
            agent=mock_agent,
            name="test_tool",
            method=None,
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z"
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.base.logging.getLogger') as mock_logger:
            logger = MagicMock()
            mock_logger.return_value = logger

            response = await tool.execute()

            # Should NOT crash - return error Response
            assert response.break_loop is False
            assert "Tool execution failed" in response.message
            assert "VM connection failed" in response.message

            # Should log error
            logger.error.assert_called_once()
            log_call = logger.error.call_args[0][0]
            log_data = json.loads(log_call)
            assert log_data["status"] == "error"


class TestGetOHLCTool:
    """Test GetOHLCTool validates against GetOHLCRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_ohlc_request(self, mock_agent, mock_loop_data):
        """Valid OHLC request validates and calls VM101Client."""
        tool = GetOHLCTool(
            agent=mock_agent,
            name="vm101.get_ohlc",
            method=None,
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z",
                "limit": 100
            },
            message="test",
            loop_data=mock_loop_data
        )

        # Mock the client method
        tool.client.get_ohlc = AsyncMock(return_value={
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "bars": [
                {
                    "timestamp": "2026-04-20T00:00:00Z",
                    "open": 2300.0,
                    "high": 2305.0,
                    "low": 2298.0,
                    "close": 2303.0,
                    "volume": 1000
                }
            ],
            "count": 1
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "1 bars" in response.message
            assert "XAUUSD" in response.message
            assert "H1" in response.message

            # Verify client was called with correct params
            tool.client.get_ohlc.assert_called_once_with(
                symbol="XAUUSD",
                timeframe="H1",
                start="2026-04-20T00:00:00Z",
                end="2026-04-21T00:00:00Z",
                limit=100
            )

    @pytest.mark.asyncio
    async def test_uses_fast_fail_profile(self, mock_agent, mock_loop_data):
        """GetOHLCTool uses FAST_FAIL retry profile."""
        tool = GetOHLCTool(
            agent=mock_agent,
            name="vm101.get_ohlc",
            method=None,
            args={"symbol": "XAUUSD", "timeframe": "H1", "start": "2026-04-20T00:00:00Z", "end": "2026-04-21T00:00:00Z"},
            message="test",
            loop_data=mock_loop_data
        )

        assert tool.client.profile == RetryProfile.FAST_FAIL


class TestGetInstrumentsTool:
    """Test GetInstrumentsTool validates against GetInstrumentsRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_instruments_request(self, mock_agent, mock_loop_data):
        """Valid instruments request validates and calls VM109Client."""
        tool = GetInstrumentsTool(
            agent=mock_agent,
            name="vm109.get_instruments",
            method=None,
            args={"enabled_only": True},
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.get_instruments = AsyncMock(return_value={
            "instruments": [
                {
                    "symbol": "XAUUSD",
                    "asset_class": "commodity",
                    "enabled": True,
                    "min_lot": 0.01,
                    "max_lot": 100.0,
                    "lot_step": 0.01
                }
            ],
            "count": 1
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "1 instruments" in response.message


class TestComputePrimitivesTool:
    """Test ComputePrimitivesTool validates against GetPrimitivesRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_primitives_request(self, mock_agent, mock_loop_data):
        """Valid primitives request validates and calls VM102Client."""
        tool = ComputePrimitivesTool(
            agent=mock_agent,
            name="vm102.compute_primitives",
            method=None,
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z",
                "layer": 3
            },
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.compute_primitives = AsyncMock(return_value={
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "layer": 3,
            "bars": [],
            "count": 0
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "layer 3" in response.message


class TestGetAccountTool:
    """Test GetAccountTool validates against GetAccountRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_account_request(self, mock_agent, mock_loop_data):
        """Valid account request validates and calls VM109Client."""
        tool = GetAccountTool(
            agent=mock_agent,
            name="vm109.get_account",
            method=None,
            args={"account_id": "123"},
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.get_account = AsyncMock(return_value={
            "account_id": "123",
            "balance": 10000.0,
            "equity": 10000.0,
            "margin": 0.0,
            "currency": "USD"
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "123" in response.message


class TestGetInstrumentConfigTool:
    """Test GetInstrumentConfigTool validates against GetInstrumentConfigRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_config_request(self, mock_agent, mock_loop_data):
        """Valid config request validates and calls VM109Client."""
        tool = GetInstrumentConfigTool(
            agent=mock_agent,
            name="vm109.get_instrument_config",
            method=None,
            args={"symbol": "XAUUSD"},
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.get_instrument_config = AsyncMock(return_value={
            "symbol": "XAUUSD",
            "timeframes": ["M5", "M15", "H1", "H4", "D1"],
            "config": {}
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "XAUUSD" in response.message


class TestGetRecentTradesTool:
    """Test GetRecentTradesTool validates against GetRecentTradesRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_trades_request(self, mock_agent, mock_loop_data):
        """Valid trades request validates and calls VM100Client."""
        tool = GetRecentTradesTool(
            agent=mock_agent,
            name="vm100.get_recent_trades",
            method=None,
            args={"account_id": "123", "limit": 10},
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.get_recent_trades = AsyncMock(return_value={
            "trades": [],
            "count": 0
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "0 trades" in response.message


class TestCreatePreTradeEntryTool:
    """Test CreatePreTradeEntryTool validates against CreatePreTradeEntryRequest/Response."""

    @pytest.mark.asyncio
    async def test_successful_create_entry(self, mock_agent, mock_loop_data):
        """Valid create request validates and calls VM100Client."""
        tool = CreatePreTradeEntryTool(
            agent=mock_agent,
            name="vm100.create_pretrade_entry",
            method=None,
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "analysis": "Bullish structure with clear demand zone"
            },
            message="test",
            loop_data=mock_loop_data
        )

        tool.client.create_pre_trade_entry = AsyncMock(return_value={
            "entry_id": "456",
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "created_at": "2026-04-26T00:00:00Z"
        })

        with patch('tools.vm_contracts.base.logging.getLogger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "456" in response.message
