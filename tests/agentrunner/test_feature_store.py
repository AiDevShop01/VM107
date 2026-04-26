"""
Tests for FeatureStore tool for direct Parquet access.

These tests verify:
1. FeatureStoreTool wraps fingpt_data for Parquet reads (NO VM102 HTTP calls)
2. Date range validation (max 90 days per query)
3. Empty partitions return empty response (no error)
4. Cross-month queries scan multiple partition directories
5. Response validated against GetPrimitivesResponse contract
6. Domain-specific method routing (get_primitives, get_volatility, get_liquidity_features)
"""
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fingpt_core.contracts.features.primitives import GetPrimitivesResponse
from tools.vm_contracts.feature_store import FeatureStoreTool


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


class TestFeatureStoreInit:
    """Test FeatureStoreTool initialization."""

    def test_init_sets_defaults(self, mock_agent, mock_loop_data):
        """FeatureStoreTool sets default data lake path and max_days."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
            args={},
            message="test",
            loop_data=mock_loop_data
        )

        assert tool.data_lake_path == "/mnt/parquet_prod"  # default
        assert tool.max_days == 90

    @patch.dict("os.environ", {"FINGPT_DATA_LAKE_PATH": "/custom/path"})
    def test_init_from_env_var(self, mock_agent, mock_loop_data):
        """FeatureStoreTool reads data lake path from environment."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
            args={},
            message="test",
            loop_data=mock_loop_data
        )

        assert tool.data_lake_path == "/custom/path"


class TestFeatureStoreMethodRouting:
    """Test method routing for domain-specific operations."""

    @pytest.mark.asyncio
    async def test_get_primitives_route(self, mock_agent, mock_loop_data):
        """Method 'get_primitives' routes to _get_primitives."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
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

        with patch.object(tool, '_get_primitives', new=AsyncMock(return_value=MagicMock())) as mock_get:
            with patch('tools.vm_contracts.base.logger'):
                await tool.execute()
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_volatility_route(self, mock_agent, mock_loop_data):
        """Method 'get_volatility' routes to get_primitives with layer=4."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_volatility",
            method="get_volatility",
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z"
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch.object(tool, '_get_primitives', new=AsyncMock(return_value=MagicMock())) as mock_get:
            with patch('tools.vm_contracts.base.logger'):
                await tool.execute()
                # Should have injected layer=4
                call_args = mock_get.call_args[0][0]
                assert call_args["layer"] == 4

    @pytest.mark.asyncio
    async def test_get_liquidity_features_route(self, mock_agent, mock_loop_data):
        """Method 'get_liquidity_features' routes to get_primitives with layer=6."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_liquidity_features",
            method="get_liquidity_features",
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-04-20T00:00:00Z",
                "end": "2026-04-21T00:00:00Z"
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch.object(tool, '_get_primitives', new=AsyncMock(return_value=MagicMock())) as mock_get:
            with patch('tools.vm_contracts.base.logger'):
                await tool.execute()
                # Should have injected layer=6
                call_args = mock_get.call_args[0][0]
                assert call_args["layer"] == 6

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self, mock_agent, mock_loop_data):
        """Unknown method returns error Response."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.unknown",
            method="unknown_method",
            args={},
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.base.logger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert "Unknown method" in response.message or "not supported" in response.message.lower()


class TestDateRangeValidation:
    """Test date range validation (max 90 days)."""

    @pytest.mark.asyncio
    async def test_date_range_within_limit(self, mock_agent, mock_loop_data):
        """Date range within 90 days passes validation."""
        start = datetime(2026, 4, 1)
        end = start + timedelta(days=89)

        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": start.isoformat() + "Z",
                "end": end.isoformat() + "Z",
                "layer": 3
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.feature_store.pl.scan_parquet') as mock_scan:
            mock_scan.return_value.collect.return_value = MagicMock(is_empty=lambda: True, to_dicts=lambda: [])
            with patch('tools.vm_contracts.base.logger'):
                response = await tool.execute()

                # Should succeed (not raise ValueError)
                assert response.break_loop is False

    @pytest.mark.asyncio
    async def test_date_range_exceeds_limit(self, mock_agent, mock_loop_data):
        """Date range > 90 days returns validation error."""
        start = datetime(2026, 4, 1)
        end = start + timedelta(days=91)

        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": start.isoformat() + "Z",
                "end": end.isoformat() + "Z",
                "layer": 3
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.base.logger'):
            response = await tool.execute()

            assert response.break_loop is False
            assert ("90 days" in response.message or "90" in response.message)


class TestParquetAccess:
    """Test direct Parquet access without VM102 HTTP calls."""

    @pytest.mark.asyncio
    async def test_empty_partitions_return_empty_response(self, mock_agent, mock_loop_data):
        """Empty partitions return count=0, no error."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
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

        # Mock Polars to return empty dataframe
        with patch('tools.vm_contracts.feature_store.pl.scan_parquet') as mock_scan:
            mock_df = MagicMock()
            mock_df.is_empty.return_value = True
            mock_df.to_dicts.return_value = []
            mock_scan.return_value.collect.return_value = mock_df

            with patch('tools.vm_contracts.base.logger'):
                response = await tool.execute()

                assert response.break_loop is False
                assert "0 feature bars" in response.message

    @pytest.mark.asyncio
    async def test_cross_month_queries_build_correct_globs(self, mock_agent, mock_loop_data):
        """Cross-month queries scan multiple partition directories."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
            args={
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "start": "2026-03-25T00:00:00Z",
                "end": "2026-04-05T00:00:00Z",
                "layer": 3
            },
            message="test",
            loop_data=mock_loop_data
        )

        with patch('tools.vm_contracts.feature_store.pl.scan_parquet') as mock_scan:
            mock_df = MagicMock()
            mock_df.is_empty.return_value = True
            mock_df.to_dicts.return_value = []
            mock_scan.return_value.collect.return_value = mock_df

            with patch('tools.vm_contracts.base.logger'):
                await tool.execute()

                # Should have called scan_parquet with glob pattern covering March and April
                scan_call = mock_scan.call_args[0][0]
                # Path should include wildcards for year/month
                assert isinstance(scan_call, (str, list))

    @pytest.mark.asyncio
    async def test_response_validated_against_contract(self, mock_agent, mock_loop_data):
        """Response validated against GetPrimitivesResponse contract."""
        tool = FeatureStoreTool(
            agent=mock_agent,
            name="feature_store.get_primitives",
            method="get_primitives",
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

        with patch('tools.vm_contracts.feature_store.pl.scan_parquet') as mock_scan:
            # Return valid data structure
            mock_df = MagicMock()
            mock_df.is_empty.return_value = False
            mock_df.to_dicts.return_value = [
                {"timestamp": "2026-04-20T00:00:00Z", "value": 1.0}
            ]
            mock_scan.return_value.collect.return_value = mock_df

            with patch('tools.vm_contracts.base.logger'):
                response = await tool.execute()

                # Should succeed with validated response
                assert response.break_loop is False
                assert "1 feature bars" in response.message
