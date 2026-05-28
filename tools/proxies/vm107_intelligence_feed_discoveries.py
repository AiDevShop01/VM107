"""Phase 70.5 Decision 18 — proxy for vm107.intelligence_feed.discoveries.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own discoveries intelligence feed endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — vm107.intelligence_feed.discoveries endpoint exists (Phase 66).
Note: VM107 self-proxy via Vm107SelfClient reading VM107_API_URL.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient


class IntelligenceFeedItem(BaseModel):
    """Single intelligence feed item."""

    model_config = ConfigDict(extra="allow")

    item_id: str | None = None
    category: str | None = None  # "discoveries"
    headline: str | None = None
    body: str | None = None
    relevance_score: float | None = None
    novelty_gated: bool = False


class Vm107IntelligenceFeedDiscoveriesPayload(BaseModel):
    """Typed payload for vm107.intelligence_feed.discoveries proxy."""

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    items: list[IntelligenceFeedItem] = Field(default_factory=list)
    state: str | None = None
    account_id: int | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    state: str = "open",
    account_id: int | None = None,
    **kwargs,
) -> Vm107IntelligenceFeedDiscoveriesPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        state: Trading state (pre/open/active_supervision/mid/close/review).
        account_id: Account ID for discoveries scope.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {"state": state}
    if account_id is not None:
        params["account"] = account_id

    response = await client.get("api/v1/intelligence_feed/discoveries", params=params)

    raw_items = response if isinstance(response, list) else response.get("items", [])
    items = [IntelligenceFeedItem(**i) for i in raw_items if isinstance(i, dict)]

    return Vm107IntelligenceFeedDiscoveriesPayload(
        items=items,
        state=state,
        account_id=account_id,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if items else "none",
                freshness_observed_seconds=120,
                missing_fields=() if items else ("items",),
                is_deterministic=False,  # LLM novelty enrichment is non-deterministic
            ),
            citations=(),
            assumptions=(
                "Discoveries scope: last 10 trades + open positions (NOT session-bounded)",
                "Novelty gate: strict — items only shown when genuinely new insight",
                "LLM enrichment additive only; base deterministic path always runs",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 intelligence_feed/discoveries endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No discoveries found — normal for new accounts or clean history",
                ),
            ),
        ),
    )
