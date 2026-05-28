"""Phase 70.5 Decision 18 — proxy for vm102.risk_metrics.snapshot.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM102's risk metrics snapshot endpoint, returns a typed ToolPayload,
and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM102 /api/v1/risk/snapshot endpoint exists (Phase 66).
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102RiskMetricsSnapshotPayload(BaseModel):
    """Typed payload for vm102.risk_metrics.snapshot proxy.

    Scope: basic portfolio risk only.
    Forbidden: Monte Carlo, EVT tails, Stressed VaR, Intraday VaR, etc.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    account_id: int | None = None
    snapshot_id: str | int | None = None
    computed_at: datetime | str | None = None
    snapshot_ttl_seconds: int | None = None
    open_position_count: int | None = None
    total_exposure_pct: float | None = None
    daily_pnl: float | None = None
    drawdown_pct: float | None = None
    risk_score: float | None = None
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    force_compute: bool = False,
    **kwargs,
) -> Vm102RiskMetricsSnapshotPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        account_id: Account ID to scope the risk snapshot.
        force_compute: If True, call POST /compute for fresh synchronous computation.
                       Default False uses GET for pre-computed snapshot.
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id

    if force_compute:
        response = await client.post(
            "api/v1/risk/snapshot/compute",
            json_data={"account_id": account_id},
        )
    else:
        response = await client.get("api/v1/risk/snapshot", params=params)

    return Vm102RiskMetricsSnapshotPayload(
        account_id=account_id,
        snapshot_id=response.get("snapshot_id") or response.get("id"),
        computed_at=response.get("computed_at"),
        snapshot_ttl_seconds=response.get("snapshot_ttl_seconds"),
        open_position_count=response.get("open_position_count"),
        total_exposure_pct=response.get("total_exposure_pct"),
        daily_pnl=response.get("daily_pnl"),
        drawdown_pct=response.get("drawdown_pct"),
        risk_score=response.get("risk_score"),
        _demo=response.get("_demo", False),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=response.get("snapshot_ttl_seconds", 300),
                missing_fields=(),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "Scope lock: basic portfolio risk only — no Monte Carlo, EVT, Stressed VaR",
                "Bounded context: no user preference or behavioral data here (lives in VM100)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 risk/snapshot endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No risk snapshot found for account",
                ),
                FailureMode(
                    code=FailureModeCode.DATA_STALE,
                    detail="Pre-computed snapshot exceeded TTL — use force_compute=True",
                ),
            ),
        ),
    )
