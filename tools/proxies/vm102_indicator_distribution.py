"""Phase 89.1 Option-B — proxy for vm102.indicator_distribution.

Calls GET /api/v2/indicator/{id}/distribution on VM102.
There are TWO distribution endpoints:
  - Phase 85: /api/v2/indicator/{id}/distribution — surprise distribution
    (actual - forecast histogram, p10/p50/p90, percentile_rank)
  - Phase 86: /api/v2/analytics/indicator/{id}/distribution — standalone
    value distribution (histogram of actual values, zscore, percentile_of_latest)

This proxy calls the Phase 85 surprise-distribution endpoint (registered as
vm102.indicator_distribution in the registry). The Phase 86 endpoint is a
separate tool not yet needed by macro_investigator's allowed_tools list.

Status: real — VM102 Phase 85 endpoint exists and is auth-guarded.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102IndicatorDistributionPayload(BaseModel):
    """Typed payload for vm102.indicator_distribution proxy.

    Maps down from VM102's DistributionResponse (Phase 85 §5.3).
    surprise_distribution: {bins: [{lower, upper, count}], p10, p50, p90}
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    surprise_distribution: dict[str, Any] | None = None  # {bins, p10, p50, p90}
    current_release_percentile: float | None = None
    cached_at: datetime | str | None = None
    ttl_seconds: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    **kwargs,
) -> Vm102IndicatorDistributionPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/indicator/{indicator_id}/distribution",
        )
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "not found" in exc_str.lower():
            code = FailureModeCode.NO_MATCH_FOUND
            detail = f"Indicator {indicator_id!r} not found or has no released events on VM102"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 indicator/{indicator_id}/distribution"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 indicator/{indicator_id}/distribution unavailable: {exc_str[:120]}"

        return Vm102IndicatorDistributionPayload(
            indicator_id=indicator_id,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("surprise_distribution", "current_release_percentile"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    return Vm102IndicatorDistributionPayload(
        indicator_id=response.get("indicator_id", indicator_id),
        surprise_distribution=response.get("surprise_distribution"),
        current_release_percentile=response.get("current_release_percentile"),
        cached_at=response.get("cached_at"),
        ttl_seconds=response.get("ttl_seconds"),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=response.get("ttl_seconds", 1800),
                missing_fields=(),
                is_deterministic=True,
            ),
            assumptions=(
                "DistributionResponse §5.3: current release EXCLUDED from the distribution it is ranked against",
                "surprise_distribution uses N_BINS=10 fixed bins for cache-key stability",
                "current_release_percentile=50.0 when insufficient historical releases (< 2)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 indicator/distribution endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"Indicator {indicator_id!r} not found or has no released events",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="Empty distribution returned — fewer than 2 historical releases with forecasts",
                ),
            ),
        ),
    )
