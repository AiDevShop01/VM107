"""Phase 70.5 Decision 18 — proxy for vm107.narratives.global.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own global narratives endpoint, returns a typed ToolPayload,
and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM107 global narratives emitter exists (Phase 66).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient


class Vm107NarrativesGlobalPayload(BaseModel):
    """Typed payload for vm107.narratives.global proxy.

    One evolving GlobalNarrative paragraph per trading state.
    Deterministic template baseline with novelty-gated LLM enrichment.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    state: str | None = None
    deterministic_base_summary: str | None = None
    llm_enriched_summary: str | None = None
    refresh_reason: str | None = None
    tier: int | None = None  # 1/2/3 graceful degradation
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    state: str = "open",
    refresh_reason: str | None = None,
    **kwargs,
) -> Vm107NarrativesGlobalPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        state: Trading state (pre/open/active_supervision/mid/close/review).
        refresh_reason: Optional refresh trigger (MACRO_EVENT/RISK_ESCALATION/etc.).
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {"state": state}
    if refresh_reason:
        params["refresh_reason"] = refresh_reason

    response = await client.get("api/v1/narratives/global", params=params)

    tier = response.get("tier", 1) if isinstance(response, dict) else 1
    demo = response.get("_demo", False) if isinstance(response, dict) else False

    return Vm107NarrativesGlobalPayload(
        state=state,
        deterministic_base_summary=response.get("deterministic_base_summary") if isinstance(response, dict) else None,
        llm_enriched_summary=response.get("llm_enriched_summary") if isinstance(response, dict) else None,
        refresh_reason=refresh_reason,
        tier=tier,
        _demo=demo,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if tier == 1 else ("partial" if tier == 2 else "sparse"),
                freshness_observed_seconds=60 if state == "open" else 300,
                missing_fields=(),
                is_deterministic=False,  # LLM enrichment when novelty threshold crossed
            ),
            citations=(),
            assumptions=(
                "One paragraph per state; refresh cadence varies (OPEN 60s, PRE 5m, CLOSE 5m)",
                "Tier 1/2/3 graceful degradation; only Tier 3 reverts _demo=True",
                "Novelty gate prevents duplicate LLM output",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 narratives/global emitter timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="Narrative tier degraded — upstream sources partially unavailable",
                ),
            ),
        ),
    )
