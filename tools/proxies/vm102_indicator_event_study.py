"""Phase 89.1 Option-B — proxy for vm102.indicator_event_study.

Calls GET /api/v2/analytics/indicator/{id}/event-study on VM102 (Phase 86).
Returns typed Vm102IndicatorEventStudyPayload with mean-return curves per asset
around CPI beat/miss events.

URL NOTE: Phase 86 analytics endpoints are at /api/v2/analytics/indicator/{id}/...
(prefix /v2/analytics) NOT /api/v2/indicator/{id}/... (Phase 85 prefix).
See VM102/backend/api/views.py line 128:
  api.add_router("/v2/analytics", macro_analytics_router, ...)

Status: real — VM102 endpoint exists (Phase 86, tested in
VM102/backend/tests/phase86/test_event_study_api.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102IndicatorEventStudyPayload(BaseModel):
    """Typed payload for vm102.indicator_event_study proxy.

    Maps down from VM102's Phase 86 event-study response envelope.
    result.curves: list of {asset_id, points: [{day, mean_return, ...}]}
    result.sample_size: number of events found (beats/misses matching threshold)
    result.period: 'YYYY-MM-DD–YYYY-MM-DD' coverage string
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    curves: list[dict[str, Any]] = Field(default_factory=list)
    sample_size: int | None = None
    period: str | None = None
    envelope_meta: dict[str, Any] | None = None  # raw Phase 70.5 envelope sub-key
    error: dict[str, Any] | None = None  # non-None on domain errors (sample too small)
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    threshold: float = 0.2,
    direction: Literal["beat", "miss"] = "beat",
    assets: str = "gold",
    pre: int = 5,
    post: int = 10,
    **kwargs,
) -> Vm102IndicatorEventStudyPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL).
        threshold: Surprise magnitude threshold in [0.0, 1.0] (default 0.2).
        direction: 'beat' (actual > forecast + threshold) or 'miss'.
        assets: Comma-separated asset slugs (max 5): gold, eur, jpy, nasdaq.
        pre: Days before event to include in window (0–30, default 5).
        post: Days after event to include in window (0–30, default 10).
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    params = {
        "threshold": threshold,
        "direction": direction,
        "assets": assets,
        "pre": pre,
        "post": post,
    }

    try:
        response = await client.get(
            f"api/v2/analytics/indicator/{indicator_id}/event-study",
            params=params,
        )
    except Exception as exc:
        exc_str = str(exc)
        if "400" in exc_str:
            # UnknownAsset or TooManyAssets or UnknownIndicator
            code = FailureModeCode.VALIDATION_FAILED
            detail = f"VM102 event-study rejected request for {indicator_id!r}: {exc_str[:120]}"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 analytics/indicator/{indicator_id}/event-study"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 analytics/indicator/{indicator_id}/event-study unavailable: {exc_str[:120]}"

        return Vm102IndicatorEventStudyPayload(
            indicator_id=indicator_id,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("curves", "sample_size", "period"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    # Phase 86 response shape: {envelope: {...}, result: {curves, sample_size, period}, error: None|{code, meta}}
    envelope_meta = response.get("envelope")
    error = response.get("error")
    result = response.get("result") or {}

    # EventStudySampleTooSmall returns HTTP 200 with error populated — surface cleanly
    if error:
        return Vm102IndicatorEventStudyPayload(
            indicator_id=indicator_id,
            envelope_meta=envelope_meta,
            error=error,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="sparse",
                    freshness_observed_seconds=None,
                    missing_fields=("curves",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(
                        code=FailureModeCode.INSUFFICIENT_CONTEXT,
                        detail=f"VM102 event-study domain error: {error.get('code', 'unknown')}",
                    ),
                ),
            ),
        )

    return Vm102IndicatorEventStudyPayload(
        indicator_id=indicator_id,
        curves=result.get("curves") or [],
        sample_size=result.get("sample_size"),
        period=result.get("period"),
        envelope_meta=envelope_meta,
        error=None,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if (result.get("sample_size") or 0) > 20 else "partial",
                freshness_observed_seconds=None,  # analytics computed on demand
                missing_fields=(),
                is_deterministic=True,
            ),
            assumptions=(
                "Phase 86 /analytics/... prefix — NOT /indicator/... (different URL tree)",
                "HTTP 200 with error field = EventStudySampleTooSmall (domain error, not server bug)",
                "assets slug map: gold=XAUUSD, eur=EURUSD, jpy=USDJPY, nasdaq=NAS100 (server-side)",
                "max 5 assets per request — TooManyAssets returned as HTTP 400 otherwise",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 analytics/event-study endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.INSUFFICIENT_CONTEXT,
                    detail="EventStudySampleTooSmall — fewer than 5 events match threshold+direction",
                ),
                FailureMode(
                    code=FailureModeCode.VALIDATION_FAILED,
                    detail="UnknownAsset or TooManyAssets (>5) — check assets parameter",
                ),
            ),
        ),
    )
