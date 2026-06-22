"""Phase 89.1 Option-B — proxy for vm102.indicator_history.

Calls GET /api/v2/indicator/{id}/history on VM102 (Phase 85 endpoint).
Returns typed Vm102IndicatorHistoryPayload with series + overlay bands.

Status: real — VM102 endpoint exists (Phase 85, tested in
VM102/backend/tests/phase85/test_indicator_history_api.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

ALLOWED_RANGES = frozenset({"1Y", "5Y", "10Y", "MAX"})


class HistoryOverlaysBound(BaseModel):
    """Overlay bands returned by VM102 (recession, rate-hike, QE windows)."""

    model_config = ConfigDict(extra="allow")

    recessions: list[dict[str, Any]] = Field(default_factory=list)
    rate_hikes: list[dict[str, Any]] = Field(default_factory=list)
    qe_periods: list[dict[str, Any]] = Field(default_factory=list)


class Vm102IndicatorHistoryPayload(BaseModel):
    """Typed payload for vm102.indicator_history proxy.

    Maps down from VM102's HistoryResponse (Phase 85 §5.1).
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    range: str = "5Y"
    series: list[dict[str, Any]] = Field(default_factory=list)
    overlays: HistoryOverlaysBound = Field(default_factory=HistoryOverlaysBound)
    cached_at: datetime | str | None = None
    ttl_seconds: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    range: str = "5Y",
    overlays: str = "recession,rate_hike,qe",
    **kwargs,
) -> Vm102IndicatorHistoryPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
        range: Time range — one of 1Y, 5Y, 10Y, MAX. Defaults to 5Y.
        overlays: Comma-separated overlay types (passed through to VM102).
    """
    if range not in ALLOWED_RANGES:
        return Vm102IndicatorHistoryPayload(
            indicator_id=indicator_id,
            range=range,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("series", "overlays"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(
                        code=FailureModeCode.VALIDATION_FAILED,
                        detail=f"range={range!r} not in {sorted(ALLOWED_RANGES)}",
                    ),
                ),
            ),
        )

    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/indicator/{indicator_id}/history",
            params={"range": range, "overlays": overlays},
        )
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "not found" in exc_str.lower():
            code = FailureModeCode.NO_MATCH_FOUND
            detail = f"Indicator {indicator_id!r} not found on VM102"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 indicator/{indicator_id}/history"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 indicator/{indicator_id}/history unavailable: {exc_str[:120]}"

        return Vm102IndicatorHistoryPayload(
            indicator_id=indicator_id,
            range=range,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("series", "overlays"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    raw_overlays = response.get("overlays") or {}
    return Vm102IndicatorHistoryPayload(
        indicator_id=response.get("indicator_id", indicator_id),
        range=response.get("range", range),
        series=response.get("series") or [],
        overlays=HistoryOverlaysBound(
            recessions=raw_overlays.get("recessions") or [],
            rate_hikes=raw_overlays.get("rate_hikes") or [],
            qe_periods=raw_overlays.get("qe_periods") or [],
        ),
        cached_at=response.get("cached_at"),
        ttl_seconds=response.get("ttl_seconds"),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=response.get("ttl_seconds", 3600),
                missing_fields=(),
                is_deterministic=True,
            ),
            assumptions=(
                "HistoryResponse §5.1: series ordered ASC by event_date for chart rendering",
                "Overlays are US-macro bands (NBER recessions, FOMC hikes, QE windows)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 indicator/history endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"Indicator {indicator_id!r} not found in ref_economic_indicators",
                ),
            ),
        ),
    )
