"""Phase 70.5 Decision 18 — proxy for vm100.behavioral_edges.for_execution.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM100's behavioral edges endpoint, returns a typed ToolPayload,
and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM100 behavioral edges endpoint exists (Phase 66 / Phase 54 ext).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm100_client import VM100Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class BehavioralNudgeItem(BaseModel):
    """Single behavioral nudge from VM100 BehavioralEdgesService."""

    model_config = ConfigDict(extra="allow")

    nudge_id: str | int | None = None
    severity: str | None = None  # INFO / CAUTION / WARNING
    message: str | None = None
    edge_type: str | None = None
    trade_ids: list[str | int] = Field(default_factory=list)


class Vm100BehavioralEdgesPayload(BaseModel):
    """Typed payload for vm100.behavioral_edges.for_execution proxy."""

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    nudges: list[BehavioralNudgeItem] = Field(default_factory=list)
    account_id: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    **kwargs,
) -> Vm100BehavioralEdgesPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        account_id: Account ID to scope behavioral analysis.
    """
    client = VM100Client()  # raises RuntimeError if VM100_API_URL unset

    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id

    response = await client.get(
        "api/v1/analytics/behavioral-edges/for-execution",
        params=params,
    )
    raw_nudges = response if isinstance(response, list) else response.get("nudges", [])
    nudges = [BehavioralNudgeItem(**n) for n in raw_nudges if isinstance(n, dict)]

    return Vm100BehavioralEdgesPayload(
        nudges=nudges,
        account_id=account_id,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=300,
                missing_fields=(),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "Behavioral edges derived from last 10 trades + open positions",
                "BLOCK severity excluded (pre-trade gate responsibility)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 behavioral-edges/for-execution endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No behavioral nudges found for account in recent trade window",
                ),
            ),
        ),
    )
