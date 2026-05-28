"""Phase 70.5 Decision 18 — proxy for vm107.intelligence_feed.macro.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own macro intelligence feed endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — vm107.intelligence_feed.macro endpoint exists (Phase 66).
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


class MacroIntelligenceFeedItem(BaseModel):
    """Single macro intelligence feed item."""

    model_config = ConfigDict(extra="allow")

    item_id: str | None = None
    category: str = "macro"
    headline: str | None = None
    body: str | None = None
    relevance_score: float | None = None
    source: str | None = None


class Vm107IntelligenceFeedMacroPayload(BaseModel):
    """Typed payload for vm107.intelligence_feed.macro proxy."""

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    items: list[MacroIntelligenceFeedItem] = Field(default_factory=list)
    state: str | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    state: str = "open",
    **kwargs,
) -> Vm107IntelligenceFeedMacroPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        state: Trading state (pre/open/active_supervision/mid/close/review).
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    response = await client.get(
        "api/v1/intelligence_feed/macro",
        params={"state": state},
    )

    raw_items = response if isinstance(response, list) else response.get("items", [])
    items = [MacroIntelligenceFeedItem(**i) for i in raw_items if isinstance(i, dict)]

    return Vm107IntelligenceFeedMacroPayload(
        items=items,
        state=state,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if items else "partial",
                freshness_observed_seconds=120,
                missing_fields=(),
                is_deterministic=False,  # LLM novelty enrichment is non-deterministic
            ),
            citations=(),
            assumptions=(
                "MACRO items are forward-looking (what is coming) — max 10 items",
                "Novelty engine suppresses duplicate macro items",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 intelligence_feed/macro endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No macro intelligence items for current trading state",
                ),
            ),
        ),
    )
