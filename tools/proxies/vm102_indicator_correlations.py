"""Phase 89.1 Option-B — proxy for vm102.indicator_correlations.

Calls GET /api/v2/analytics/indicator/{id}/correlations on VM102 (Phase 86).
Returns typed Vm102IndicatorCorrelationsPayload with rolling Pearson correlation
time-series between an indicator and an asset.

URL NOTE: Phase 86 analytics endpoints are at /api/v2/analytics/indicator/{id}/...
(prefix /v2/analytics) NOT /api/v2/indicator/{id}/... (Phase 85 prefix).
See VM102/backend/api/views.py line 128:
  api.add_router("/v2/analytics", macro_analytics_router, ...)

Status: real — VM102 endpoint exists (Phase 86, tested in
VM102/backend/tests/phase86/test_correlations_api.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

_ALLOWED_WINDOWS = frozenset({50, 100, 200, 500})


class Vm102IndicatorCorrelationsPayload(BaseModel):
    """Typed payload for vm102.indicator_correlations proxy.

    Maps down from VM102's Phase 86 correlations response envelope.
    result.series: list of {date: str, corr: float} — values in [-1.0, +1.0].
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    asset: str
    window: int = 200
    series: list[dict[str, Any]] = Field(default_factory=list)
    envelope_meta: dict[str, Any] | None = None  # raw Phase 70.5 envelope sub-key
    error: dict[str, Any] | None = None  # non-None on domain errors
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    asset: str = "gold",
    window: int = 200,
    **kwargs,
) -> Vm102IndicatorCorrelationsPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
        asset: Asset slug — one of: gold, eur, jpy, nasdaq, or canonical symbol.
        window: Rolling correlation window in days. Must be one of {50, 100, 200, 500}.
                Defaults to 200.
    """
    if window not in _ALLOWED_WINDOWS:
        return Vm102IndicatorCorrelationsPayload(
            indicator_id=indicator_id,
            asset=asset,
            window=window,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("series",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(
                        code=FailureModeCode.VALIDATION_FAILED,
                        detail=f"window={window} not in allowed set {sorted(_ALLOWED_WINDOWS)}",
                    ),
                ),
            ),
        )

    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/analytics/indicator/{indicator_id}/correlations",
            params={"asset": asset, "window": window},
        )
    except Exception as exc:
        exc_str = str(exc)
        if "400" in exc_str:
            # UnknownAsset or UnknownIndicator
            code = FailureModeCode.VALIDATION_FAILED
            detail = f"VM102 correlations rejected request for {indicator_id!r}/{asset!r}: {exc_str[:120]}"
        elif "422" in exc_str:
            code = FailureModeCode.VALIDATION_FAILED
            detail = f"VM102 correlations schema error (window not in allowed set): {exc_str[:120]}"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 analytics/indicator/{indicator_id}/correlations"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 analytics/indicator/{indicator_id}/correlations unavailable: {exc_str[:120]}"

        return Vm102IndicatorCorrelationsPayload(
            indicator_id=indicator_id,
            asset=asset,
            window=window,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("series",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    # Phase 86 response shape: {envelope: {...}, result: {series: [{date, corr}]}, error: None|{code, meta}}
    envelope_meta = response.get("envelope")
    error = response.get("error")
    result = response.get("result") or {}

    if error:
        return Vm102IndicatorCorrelationsPayload(
            indicator_id=indicator_id,
            asset=asset,
            window=window,
            envelope_meta=envelope_meta,
            error=error,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("series",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(
                        code=FailureModeCode.VALIDATION_FAILED,
                        detail=f"VM102 correlations domain error: {error.get('code', 'unknown')}",
                    ),
                ),
            ),
        )

    series = result.get("series") or []
    sample_size = envelope_meta.get("provenance", {}).get("sample_size", len(series)) if envelope_meta else len(series)

    return Vm102IndicatorCorrelationsPayload(
        indicator_id=indicator_id,
        asset=asset,
        window=window,
        series=series,
        envelope_meta=envelope_meta,
        error=None,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if len(series) > 0 else "sparse",
                freshness_observed_seconds=None,  # analytics computed on demand
                missing_fields=() if series else ("series",),
                is_deterministic=True,
            ),
            assumptions=(
                "Phase 86 /analytics/... prefix — NOT /indicator/... (different URL tree)",
                "Rolling Pearson correlation — window parameter must be in {50, 100, 200, 500}",
                "asset slug map: gold=XAUUSD, eur=EURUSD, jpy=USDJPY, nasdaq=NAS100 (server-side)",
                "Empty series returned when window > history length (no error, just empty)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 analytics/correlations endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.VALIDATION_FAILED,
                    detail="UnknownAsset, UnknownIndicator, or bad window value",
                ),
            ),
        ),
    )
