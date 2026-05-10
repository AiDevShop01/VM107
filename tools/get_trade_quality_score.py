"""get_trade_quality_score — Phase 57 Plan 08.

Aggregate READ tool: reads the latest TradeAnalyticsSnapshot row for a given
execution_id and returns the overall score + 6 category score breakdown in a
structured TradeQualityScoreResult contract.

This is NOT a compute tool. It never calls VM102 or triggers an analysis run.
Its sole responsibility is to read the pre-computed snapshot row from VM100
via GET /api/journal/internal/analytics-snapshot/{execution_id}.

Architecture (CONTEXT §7):
  - VM100 = system of record (holds the TradeAnalyticsSnapshot table)
  - VM107 = system of cognition (reads it; Phase 60 mentor agents use this)
  - Single GET (no concurrent fan-out — there is one authoritative endpoint)
  - Pure read: NO INSERT, NO UPDATE, NO analysis run, NO scoring recompute

Distinction from the 7 category tools:
  - Category tools (57-01 to 57-07): COMPUTE scores from raw primitives + event timeline
  - This tool: READS the aggregate snapshot row that AnalyticsService composed

Master-plan naming (CONTEXT §9 row 6):
  get_trade_quality_score IS the master-plan name — no alias needed.
  (Alias would be circular: get_trade_quality_score → get_trade_quality_score)

Response shape: TradeQualityScoreResult (fingpt_core.contracts.analytics.snapshot):
  - execution_id, snapshot_id, scoring_ruleset_version
  - overall_score, overall_confidence
  - regime_score, liquidity_score, compression_score
  - execution_quality_score, behavioral_score, setup_quality_score
  - generated_at, analysis_version

Not-available handling:
  When VM100 returns 404 (no snapshot for this execution), the tool returns None.
  Callers MUST check for None before accessing result fields.
  When VM100 is unreachable (transport error), raises or returns None with
  a structured log entry — never crashes silently.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='get_trade_quality_score', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='get_trade_quality_score'}

result_status values: success | not_available | transport_error | validation_error

Usage:
    tool = GetTradeQualityScoreTool()
    result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")
    if result is None:
        # No snapshot exists yet — analytics run hasn't completed
        return
    print(result.overall_score, result.regime_score)

Phase 60+ usage: mentor agents call this to read existing snapshots without
recomputing. A separate `recompute_quality_score_for_ruleset_version` tool
(not in scope for Phase 57) would trigger a new analysis run.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Optional

import httpx

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.analytics.snapshot import (
    TradeQualityScoreResult,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.get_trade_quality_score")

TOOL_NAME = "get_trade_quality_score"


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope or error response."""
    return not isinstance(data, dict) or (
        isinstance(data, dict) and (
            data.get("status") == "not_available"
            or data.get("error") is not None
        )
    )


class GetTradeQualityScoreTool:
    """VM107 aggregate read tool: reads TradeAnalyticsSnapshot by execution_id.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by Phase 60 mentor agents and tested without the agent framework.

    Single GET to VM100 — no concurrent fan-out, no compute pipeline,
    no VM102 calls, no scoring recompute. Pure read.

    Registry: YAML at VM107/registry/tool/get_trade_quality_score.yaml
    Status: shipped (Phase 57-08)
    Aliases: [] (already IS the master-plan name)
    """

    def _validate_request(self, args: dict) -> dict:
        """Validate and normalize args for the snapshot read.

        Required:
            execution_id (str): UUID of the Execution to read snapshot for.

        Optional:
            scoring_ruleset_version (str): if provided, filters to that ruleset;
                if absent, returns the latest snapshot regardless of ruleset.

        Returns:
            dict with validated execution_id (str) and optional scoring_ruleset_version.

        Raises:
            ContractValidationError: if execution_id is missing or malformed.
        """
        from uuid import UUID

        execution_id = args.get("execution_id")
        if not execution_id:
            raise ContractValidationError(
                errors=["execution_id is required"],
                message="get_trade_quality_score: execution_id is required",
            )
        try:
            # Validate UUID format — raises ValueError on bad UUID
            UUID(str(execution_id))
        except (ValueError, TypeError) as e:
            raise ContractValidationError(
                errors=[f"execution_id must be a valid UUID: {execution_id!r}"],
                message=str(e),
            ) from e

        return {
            "execution_id": str(execution_id),
            "scoring_ruleset_version": args.get("scoring_ruleset_version"),
        }

    async def _call_vm(self, validated: dict) -> dict:
        """Fetch TradeAnalyticsSnapshot from VM100.

        Calls GET /api/journal/internal/analytics-snapshot/{execution_id}.
        If scoring_ruleset_version is specified, passes it as a query param
        (VM100 endpoint filters + orders by generated_at DESC).
        If not specified, VM100 returns the latest snapshot across all rulesets.

        Returns:
            dict: snapshot data on 200
            dict: {'status': 'not_available', 'reason': '...'} on 404
            dict: {'status': 'not_available', 'reason': 'transport_error'} on transport failure

        Raises:
            httpx.HTTPStatusError: on unexpected non-404, non-5xx HTTP errors.
        """
        vm100 = VM100Client(profile=RetryProfile.FAST_FAIL)
        execution_id = validated["execution_id"]
        scoring_ruleset_version = validated.get("scoring_ruleset_version")

        params = {}
        if scoring_ruleset_version:
            params["scoring_ruleset_version"] = scoring_ruleset_version

        try:
            result = await vm100.get(
                f"api/journal/internal/analytics-snapshot/{execution_id}",
                params=params if params else None,
            )
            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(
                    "get_trade_quality_score: no snapshot for execution_id=%s "
                    "(scoring_ruleset_version=%s) — returns not_available",
                    execution_id,
                    scoring_ruleset_version,
                )
                return {
                    "status": "not_available",
                    "reason": "snapshot_not_found",
                    "execution_id": execution_id,
                    "detail": "No TradeAnalyticsSnapshot found for this execution.",
                }
            if e.response.status_code >= 500:
                logger.error(
                    "get_trade_quality_score: VM100 server error %s for execution_id=%s",
                    e.response.status_code,
                    execution_id,
                )
                return {
                    "status": "not_available",
                    "reason": "vm100_server_error",
                    "detail": str(e),
                }
            raise

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(
                "get_trade_quality_score: VM100 transport error for execution_id=%s: %s",
                execution_id,
                e,
            )
            return {
                "status": "not_available",
                "reason": "vm100_transport_error",
                "detail": str(e),
            }

        finally:
            await vm100.close()

    def _validate_response(
        self, snapshot_data: dict
    ) -> Optional[TradeQualityScoreResult]:
        """Build TradeQualityScoreResult from the VM100 snapshot dict.

        Returns:
            TradeQualityScoreResult: on success.
            None: when snapshot_data is a not_available envelope.

        Raises:
            ContractValidationError: if snapshot_data has unexpected shape.
        """
        if _is_not_available(snapshot_data):
            return None

        # Map VM100 snapshot dict fields → TradeQualityScoreResult contract
        def _d(v) -> Optional[Decimal]:
            return Decimal(str(v)) if v is not None else None

        try:
            from datetime import datetime, timezone
            generated_at_raw = snapshot_data.get("generated_at")
            if generated_at_raw is None:
                raise ContractValidationError(
                    errors=["snapshot missing generated_at"],
                    message="get_trade_quality_score: invalid snapshot shape",
                )
            if isinstance(generated_at_raw, str):
                generated_at = datetime.fromisoformat(
                    generated_at_raw.replace("Z", "+00:00")
                )
            else:
                generated_at = generated_at_raw

            return TradeQualityScoreResult(
                execution_id=snapshot_data["execution_id"],
                snapshot_id=snapshot_data["id"],
                scoring_ruleset_version=snapshot_data.get(
                    "scoring_ruleset_version", "1.0.0"
                ),
                overall_score=_d(snapshot_data.get("overall_score")),
                overall_confidence=_d(snapshot_data.get("overall_confidence")),
                regime_score=_d(snapshot_data.get("regime_score")),
                liquidity_score=_d(snapshot_data.get("liquidity_score")),
                compression_score=_d(snapshot_data.get("compression_score")),
                execution_quality_score=_d(
                    snapshot_data.get("execution_quality_score")
                ),
                behavioral_score=_d(snapshot_data.get("behavioral_score")),
                setup_quality_score=_d(snapshot_data.get("setup_quality_score")),
                generated_at=generated_at,
                analysis_version=snapshot_data.get("analysis_version", 1),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ContractValidationError(
                errors=[str(e)],
                message=f"get_trade_quality_score: snapshot_data has unexpected shape: {e}",
            ) from e

    def _increment_prometheus(self, result_status: str, duration_s: float) -> None:
        """Increment Prometheus counters with bounded cardinality labels.

        result_status values: success | not_available | transport_error | validation_error
        (Pattern 26 — no unbounded label values, no execution_ids, no campaign_ids)
        """
        try:
            from journal.monitoring.post_trade_metrics import (
                vm107_analytics_tool_calls_total,
                vm107_analytics_tool_duration_seconds,
            )
            vm107_analytics_tool_calls_total.labels(
                tool=TOOL_NAME, result_status=result_status
            ).inc()
            vm107_analytics_tool_duration_seconds.labels(tool=TOOL_NAME).observe(
                duration_s
            )
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "get_trade_quality_score: Prometheus increment failed: %s", e
            )

    def run(
        self,
        execution_id: str,
        scoring_ruleset_version: Optional[str] = None,
    ) -> Optional[TradeQualityScoreResult]:
        """Synchronous entry point — reads snapshot for execution_id.

        Args:
            execution_id: UUID of the Execution to read snapshot for.
            scoring_ruleset_version: optional ruleset filter. When absent,
                returns the most recent snapshot for any ruleset version.

        Returns:
            TradeQualityScoreResult: when snapshot exists.
            None: when no snapshot exists for this execution (VM100 returned 404).

        Raises:
            ContractValidationError: on request validation failure or
                unexpected response shape.
        """
        import asyncio

        return asyncio.run(
            self.run_async(
                execution_id=execution_id,
                scoring_ruleset_version=scoring_ruleset_version,
            )
        )

    async def run_async(
        self,
        execution_id: str,
        scoring_ruleset_version: Optional[str] = None,
    ) -> Optional[TradeQualityScoreResult]:
        """Async entry point — AnalyticsService calls this inside asyncio.gather.

        Args:
            execution_id: UUID of the Execution to read snapshot for.
            scoring_ruleset_version: optional ruleset filter.

        Returns:
            TradeQualityScoreResult when snapshot exists, None otherwise.
        """
        start_time = time.monotonic()
        result_status = "success"

        try:
            # Step 1: validate request
            validated = self._validate_request(
                {
                    "execution_id": execution_id,
                    "scoring_ruleset_version": scoring_ruleset_version,
                }
            )

            # Step 2: call VM100 — single GET (pure read)
            snapshot_data = await self._call_vm(validated)

            # Step 3: validate response → TradeQualityScoreResult or None
            result = self._validate_response(snapshot_data)

            if result is None:
                result_status = "not_available"

            return result

        except ContractValidationError:
            result_status = "validation_error"
            raise

        except Exception as e:  # noqa: BLE001
            result_status = "transport_error"
            logger.error(
                "get_trade_quality_score: unexpected error for execution_id=%s: %s",
                execution_id,
                e,
                exc_info=True,
            )
            raise

        finally:
            duration_s = time.monotonic() - start_time
            self._increment_prometheus(result_status, duration_s)
