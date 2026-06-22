"""Phase 89.1 Option-B — proxy for vm102.indicator_releases.

Calls GET /api/v2/indicator/{id}/releases on VM102 (Phase 85 endpoint).
Returns typed Vm102IndicatorReleasesPayload with release records.

Status: real — VM102 endpoint exists (Phase 85, registered in
VM107/registry/tool/vm102.indicator_releases.yaml).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

DEFAULT_LIMIT = 12
MAX_LIMIT = 60


class Vm102IndicatorReleasesPayload(BaseModel):
    """Typed payload for vm102.indicator_releases proxy.

    Maps down from VM102's ReleasesResponse (Phase 85 §5.2).
    Each release record: {event_id, release_ts, previous, forecast, actual, surprise, surprise_pct}.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    releases: list[dict[str, Any]] = Field(default_factory=list)
    cached_at: datetime | str | None = None
    ttl_seconds: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    limit: int = DEFAULT_LIMIT,
    **kwargs,
) -> Vm102IndicatorReleasesPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
        limit: Number of recent releases to return (1–60, default 12).
    """
    # Clamp limit to valid range (mirrors VM102 server-side clamping)
    limit = max(1, min(limit, MAX_LIMIT))

    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/indicator/{indicator_id}/releases",
            params={"limit": limit},
        )
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "not found" in exc_str.lower():
            code = FailureModeCode.NO_MATCH_FOUND
            detail = f"Indicator {indicator_id!r} not found on VM102"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 indicator/{indicator_id}/releases"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 indicator/{indicator_id}/releases unavailable: {exc_str[:120]}"

        return Vm102IndicatorReleasesPayload(
            indicator_id=indicator_id,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("releases",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    return Vm102IndicatorReleasesPayload(
        indicator_id=response.get("indicator_id", indicator_id),
        releases=response.get("releases") or [],
        cached_at=response.get("cached_at"),
        ttl_seconds=response.get("ttl_seconds"),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=response.get("ttl_seconds", 60),
                missing_fields=(),
                is_deterministic=True,
            ),
            assumptions=(
                "ReleasesResponse §5.2: releases ordered DESC by release_ts (latest first)",
                "surprise = actual - forecast (None when forecast unavailable)",
                "previous = actual of the immediately preceding release",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 indicator/releases endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"Indicator {indicator_id!r} not found in ref_economic_indicators",
                ),
            ),
        ),
    )
