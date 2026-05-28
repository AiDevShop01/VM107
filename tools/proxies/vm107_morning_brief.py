"""Phase 70.5 Decision 18 — proxy for vm107.morning_brief.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own morning brief emitter endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM107 morning brief emitter exists (Phase 67).
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient

ConfidenceTier = Literal["FULL", "PARTIAL", "DEGRADED"]


class Vm107MorningBriefPayload(BaseModel):
    """Typed payload for vm107.morning_brief proxy.

    Deterministic base always produced; LLM enrichment additive only when
    novelty threshold is crossed.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    account_id: int | None = None
    headline: str | None = None
    body: str | None = None
    top_catalysts: list[str] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)
    confidence_tier: ConfidenceTier = "FULL"
    llm_enriched_summary: str | None = None
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    **kwargs,
) -> Vm107MorningBriefPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        account_id: Account ID for morning brief context assembly.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id

    response = await client.get("api/v1/emitters/morning_brief", params=params)

    tier = response.get("confidence_tier", "FULL") if isinstance(response, dict) else "FULL"
    demo = response.get("_demo", False) if isinstance(response, dict) else False

    return Vm107MorningBriefPayload(
        account_id=account_id,
        headline=response.get("headline") if isinstance(response, dict) else None,
        body=response.get("body") if isinstance(response, dict) else None,
        top_catalysts=response.get("top_catalysts", []) if isinstance(response, dict) else [],
        risk_alerts=response.get("risk_alerts", []) if isinstance(response, dict) else [],
        confidence_tier=tier,
        llm_enriched_summary=response.get("llm_enriched_summary") if isinstance(response, dict) else None,
        _demo=demo,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if tier == "FULL" else ("partial" if tier == "PARTIAL" else "sparse"),
                freshness_observed_seconds=300,
                missing_fields=(),
                is_deterministic=False,  # LLM enrichment when novelty threshold crossed
            ),
            citations=(),
            assumptions=(
                "Deterministic base summary ALWAYS produced — LLM enrichment is additive only",
                "Confidence tier degrades FULL/PARTIAL/DEGRADED as upstream sources go missing",
                "_demo flips True on DEGRADED tier",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 morning_brief emitter timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="Upstream sources missing — confidence tier degraded to PARTIAL or DEGRADED",
                ),
            ),
        ),
    )
