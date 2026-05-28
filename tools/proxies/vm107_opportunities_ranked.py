"""Phase 70.5 Decision 18 — proxy for vm107.opportunities.ranked.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own opportunities ranking endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM107 opportunities/ranked emitter exists (Phase 66).
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient

OpportunityTier = Literal["T1", "T2", "T3"]


class RankedOpportunity(BaseModel):
    """A single ranked trade opportunity."""

    model_config = ConfigDict(extra="allow")

    opportunity_id: str | None = None
    symbol: str | None = None
    tier: OpportunityTier = "T2"
    score: float | None = None
    setup_type: str | None = None
    regime_aligned: bool | None = None
    session_timing: str | None = None
    behavioral_edge: str | None = None
    _demo: bool = False


class Vm107OpportunitiesRankedPayload(BaseModel):
    """Typed payload for vm107.opportunities.ranked proxy.

    Tier-ranked snapshot of current trade opportunities.
    Tiers: T1 (strong conviction), T2 (valid but degraded), T3 (watch-only).
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    state: str | None = None
    account_id: int | None = None
    t1: list[RankedOpportunity] = Field(default_factory=list)
    t2: list[RankedOpportunity] = Field(default_factory=list)
    t3: list[RankedOpportunity] = Field(default_factory=list)
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    state: str = "open",
    account_id: int | None = None,
    **kwargs,
) -> Vm107OpportunitiesRankedPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        state: Trading state (pre/open/active_supervision/mid/close/review).
        account_id: Account ID for opportunity scoping.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {"state": state}
    if account_id is not None:
        params["account"] = account_id

    response = await client.get("api/v1/opportunities/ranked", params=params)

    t1 = [RankedOpportunity(**o) for o in response.get("t1", []) if isinstance(o, dict)] if isinstance(response, dict) else []
    t2 = [RankedOpportunity(**o) for o in response.get("t2", []) if isinstance(o, dict)] if isinstance(response, dict) else []
    t3 = [RankedOpportunity(**o) for o in response.get("t3", []) if isinstance(o, dict)] if isinstance(response, dict) else []
    demo = response.get("_demo", False) if isinstance(response, dict) else False

    return Vm107OpportunitiesRankedPayload(
        state=state,
        account_id=account_id,
        t1=t1,
        t2=t2,
        t3=t3,
        _demo=demo,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if (t1 or t2 or t3) else "none",
                freshness_observed_seconds=60,
                missing_fields=(),
                is_deterministic=False,  # multi-factor scoring with live market data
            ),
            citations=(),
            assumptions=(
                "Snapshot-publishing model — each call replaces previous snapshot atomically",
                "Phase 47 pre-trade evaluation gating applied at T1 boundary",
                "Graceful degradation: empty tiers with _demo=True when upstream unavailable",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 opportunities/ranked emitter timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No ranked opportunities found — all tiers empty with _demo=True",
                ),
            ),
        ),
    )
