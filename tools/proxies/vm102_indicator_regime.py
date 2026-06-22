"""Phase 89.1 Option-B — proxy for vm102.indicator_regime.

Calls GET /api/v2/indicator/{id}/regime on VM102 (Phase 85 endpoint).
Returns typed Vm102IndicatorRegimePayload with current bucket + history.

Status: real — VM102 endpoint exists (Phase 85, registered in
VM107/registry/tool/vm102.indicator_regime.yaml).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102IndicatorRegimePayload(BaseModel):
    """Typed payload for vm102.indicator_regime proxy.

    Maps down from VM102's RegimeResponse (Phase 85 §5.4).
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    indicator_id: str
    current_value: float | None = None
    current_regime: dict[str, Any] | None = None  # {label, bucket_index, bucket_lower, bucket_upper}
    regime_history: list[dict[str, Any]] = Field(default_factory=list)
    thresholds: list[dict[str, Any]] = Field(default_factory=list)
    cached_at: datetime | str | None = None
    ttl_seconds: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    indicator_id: str = "CPIAUCSL",
    **kwargs,
) -> Vm102IndicatorRegimePayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        indicator_id: FRED indicator code (e.g. CPIAUCSL, FEDFUNDS).
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            f"api/v2/indicator/{indicator_id}/regime",
        )
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "not found" in exc_str.lower():
            code = FailureModeCode.NO_MATCH_FOUND
            detail = f"Indicator {indicator_id!r} not found or has no events on VM102"
        elif "401" in exc_str or "403" in exc_str:
            code = FailureModeCode.PERMISSION_DENIED
            detail = f"Auth error calling VM102 indicator/{indicator_id}/regime"
        else:
            code = FailureModeCode.UPSTREAM_TIMEOUT
            detail = f"VM102 indicator/{indicator_id}/regime unavailable: {exc_str[:120]}"

        return Vm102IndicatorRegimePayload(
            indicator_id=indicator_id,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("current_value", "current_regime", "regime_history", "thresholds"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(code=code, detail=detail),
                ),
            ),
        )

    return Vm102IndicatorRegimePayload(
        indicator_id=response.get("indicator_id", indicator_id),
        current_value=response.get("current_value"),
        current_regime=response.get("current_regime"),
        regime_history=response.get("regime_history") or [],
        thresholds=response.get("thresholds") or [],
        cached_at=response.get("cached_at"),
        ttl_seconds=response.get("ttl_seconds"),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=response.get("ttl_seconds", 300),
                missing_fields=(),
                is_deterministic=True,
            ),
            assumptions=(
                "RegimeResponse §5.4: current_regime.label from threshold-based rule classifier",
                "regime_history covers last 24 prior releases (HISTORY_LIMIT=24)",
                "Unconfigured regime label returned when EconomicIndicator.regime_thresholds is empty",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 indicator/regime endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"Indicator {indicator_id!r} not found or has no released events",
                ),
            ),
        ),
    )
