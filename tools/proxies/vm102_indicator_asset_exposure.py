"""Phase 89.1 Option-B — proxy for vm102.indicator_asset_exposure.

Calls GET /api/v2/indicator/{id}/asset-exposure on VM102 (Phase 85 endpoint).
Returns typed Vm102IndicatorAssetExposurePayload with rolling correlation per
paired asset.

Status: real — VM102 endpoint exists (Phase 85 Plan 05, registered in
VM107/registry/tool/vm102.indicator_asset_exposure.yaml).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102IndicatorAssetExposurePayload(BaseModel):
    """Typed payload for vm102.indicator_asset_exposure proxy.

    Maps down from VM102's AssetExposureResponse (Phase 85 §5.5).
    paired_assets: list of {asset_id, asset_label, default_direction,
                            rolling_correlation, sign, strength_score}
    strength_score: 1-100 from |correlation| × 100; 0 when correlation None.
    sign: POS | NEG | MIXED (live-computed, not hand-coded).
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    computed_at: datetime | str | None = None
    window_trading_days: int | None = None
    paired_assets: list[dict[str, Any]] = Field(default_factory=list)
    cached_at: datetime | str | None = None
    ttl_seconds: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    **kwargs,
) -> Vm102IndicatorAssetExposurePayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/indicator/{indicator_id}/asset-exposure",
        )
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "not found" in exc_str.lower():
            code = FailureModeCode.NO_MATCH_FOUND
            detail = f"Indicator {indicator_id!r} not found or has no asset_exposure_pairs on VM102"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 indicator/{indicator_id}/asset-exposure"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 indicator/{indicator_id}/asset-exposure unavailable: {exc_str[:120]}"

        return Vm102IndicatorAssetExposurePayload(
            indicator_id=indicator_id,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("paired_assets",),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    return Vm102IndicatorAssetExposurePayload(
        indicator_id=response.get("indicator_id", indicator_id),
        computed_at=response.get("computed_at"),
        window_trading_days=response.get("window_trading_days"),
        paired_assets=response.get("paired_assets") or [],
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
                "AssetExposureResponse §5.5: strength_score always live-computed from |correlation|×100 (REQ-85-3)",
                "rolling_correlation=null means OHLC data was unavailable for that asset (graceful degradation)",
                "window_trading_days=200 (WINDOW_TRADING_DAYS constant)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 indicator/asset-exposure endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"Indicator {indicator_id!r} not found or has no asset_exposure_pairs",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="One or more paired assets returned rolling_correlation=null (OHLC unavailable)",
                ),
            ),
        ),
    )
