"""
FeatureStore tool for direct Parquet access.

Wraps fingpt_data for reading primitives without VM102 HTTP calls.
Uses Polars for fast Parquet I/O with Hive partition filtering.
"""
import os
from datetime import datetime
from pathlib import Path

import polars as pl

from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.features.primitives import GetPrimitivesRequest, GetPrimitivesResponse
from helpers.tool import Response
from tools.vm_contracts.base import ContractTool


class FeatureStoreTool(ContractTool):
    """
    FeatureStore tool for direct Parquet access.

    Reads primitives from Parquet files without VM102 HTTP calls.
    Uses Polars with Hive partitioning for fast partition pruning.
    Validates date ranges (max 90 days) to prevent partition explosion.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_lake_path = os.getenv("FINGPT_DATA_LAKE_PATH", "/mnt/parquet_prod")
        self.max_days = 90

    async def execute(self, **kwargs) -> Response:
        """
        Execute with method routing.

        Routes based on self.method:
        - get_primitives: Read primitives from Parquet
        - get_volatility: Delegate to get_primitives with layer=4
        - get_liquidity_features: Delegate to get_primitives with layer=6
        """
        if self.method == "get_primitives":
            return await self._get_primitives(self.args)
        elif self.method == "get_volatility":
            # Inject layer=4 for volatility
            args = {**self.args, "layer": 4}
            return await self._get_primitives(args)
        elif self.method == "get_liquidity_features":
            # Inject layer=6 for liquidity
            args = {**self.args, "layer": 6}
            return await self._get_primitives(args)
        else:
            return Response(
                message=f"Unknown method: {self.method}. Supported: get_primitives, get_volatility, get_liquidity_features",
                break_loop=False
            )

    async def _get_primitives(self, args: dict) -> Response:
        """Get primitives from Parquet using standard validation pipeline."""
        # Use base class execute to run validation pipeline
        # This is a bit of a hack - we override execute() for routing,
        # but then call the parent's validation logic here
        return await self._execute_with_validation(args)

    async def _execute_with_validation(self, args: dict) -> Response:
        """Execute with standard validation pipeline."""
        import time

        start_time = time.time()
        timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            # Validate request
            request = self._validate_request(args)

            # Call VM (in this case, read Parquet directly)
            response_data = await self._call_vm(request)

            # Validate response
            response = self._validate_response(response_data)

            # Log success
            duration_ms = int((time.time() - start_time) * 1000)
            import logging
            import json
            logger = logging.getLogger("fingpt.tools")
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
            # Validation failure
            duration_ms = int((time.time() - start_time) * 1000)
            import logging
            import json
            logger = logging.getLogger("fingpt.tools")
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
            # Execution failure
            duration_ms = int((time.time() - start_time) * 1000)
            import logging
            import json
            logger = logging.getLogger("fingpt.tools")
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

    def _validate_request(self, args: dict) -> BaseContract:
        """Validate args against GetPrimitivesRequest."""
        try:
            request = GetPrimitivesRequest(**args)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid primitives request: {e}"
            )

        # Additional date range validation
        start = datetime.fromisoformat(request.start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.end.replace("Z", "+00:00"))
        days = (end - start).days

        if days > self.max_days:
            raise ValueError(
                f"Date range too large: {days} days exceeds maximum of {self.max_days} days"
            )

        return request

    async def _call_vm(self, request: GetPrimitivesRequest) -> dict:
        """Read primitives from Parquet (no HTTP call)."""
        # Build Parquet paths with Hive partitioning
        start = datetime.fromisoformat(request.start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.end.replace("Z", "+00:00"))

        # Get year/month ranges
        year_months = self._get_year_month_ranges(start, end)

        # Build glob pattern for multiple partitions
        base_path = Path(self.data_lake_path) / "primitives" / f"layer_{request.layer}"

        # Build paths for each year/month combination
        paths = []
        for year, month in year_months:
            # Path pattern: /mnt/parquet_prod/primitives/layer_3/instrument=XAUUSD/timeframe=H1/year=2026/month=4/*.parquet
            path_pattern = (
                base_path /
                f"instrument={request.symbol}" /
                f"timeframe={request.timeframe}" /
                f"year={year}" /
                f"month={month:02d}" /
                "*.parquet"
            )
            paths.append(str(path_pattern))

        # Check if any paths exist (graceful handling of missing partitions)
        # Try to find existing parquet files
        existing_paths = []
        for p in paths:
            parent = Path(p).parent
            if parent.exists() and list(parent.glob("*.parquet")):
                existing_paths.append(p)

        if not existing_paths:
            # No data found - return empty result
            return {
                "symbol": request.symbol,
                "timeframe": request.timeframe,
                "bars": [],
                "count": 0
            }

        # Scan Parquet files with Hive partitioning
        df = pl.scan_parquet(existing_paths, hive_partitioning=True).collect()

        if df.is_empty():
            bars = []
        else:
            # Filter by timestamp range
            df = df.filter(
                (pl.col("timestamp") >= request.start) &
                (pl.col("timestamp") <= request.end)
            )
            bars = df.to_dicts()

        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "bars": bars,
            "count": len(bars)
        }

    def _validate_response(self, data: dict) -> BaseContract:
        """Validate response against GetPrimitivesResponse."""
        try:
            return GetPrimitivesResponse(**data)
        except Exception as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"Invalid primitives response: {e}"
            )

    def _format_response(self, contract: GetPrimitivesResponse) -> Response:
        """Format primitives response for agent."""
        message = f"Retrieved {contract.count} feature bars for {contract.symbol} {contract.timeframe}"
        return Response(message=message, break_loop=False)

    def _get_year_month_ranges(self, start: datetime, end: datetime) -> list[tuple[int, int]]:
        """
        Generate (year, month) tuples covering the date range.

        Args:
            start: Start datetime
            end: End datetime

        Returns:
            List of (year, month) tuples
        """
        ranges = []
        current = start.replace(day=1)  # Start of month
        end_month = end.replace(day=1)

        while current <= end_month:
            ranges.append((current.year, current.month))
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return ranges
