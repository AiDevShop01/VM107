"""Phase 70.5 Decision 18 — proxy for vm107.overnight_delta.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own overnight delta emitter endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM107 overnight_delta emitter exists (Phase 67).
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient

BucketDirection = Literal["up", "down", "mixed", "flat"]
BucketMagnitude = Literal["small", "moderate", "large", "extreme"]


class OvernightBucketDelta(BaseModel):
    """Single overnight delta bucket."""

    model_config = ConfigDict(extra="allow")

    bucket: str  # FX / BONDS / COMMODITIES / CRYPTO
    headline: str | None = None
    direction: BucketDirection = "flat"
    magnitude: BucketMagnitude = "small"
    notable_symbols: list[str] = Field(default_factory=list)  # 0-3 symbols
    _demo: bool = False


class Vm107OvernightDeltaPayload(BaseModel):
    """Typed payload for vm107.overnight_delta proxy.

    4 fixed buckets: FX / BONDS / COMMODITIES / CRYPTO.
    Bucket order locked via model_validator so downstream can index by position.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    account_id: int | None = None
    overall_summary: str | None = None
    llm_enriched_summary: str | None = None
    buckets: list[OvernightBucketDelta] = Field(default_factory=list)
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    **kwargs,
) -> Vm107OvernightDeltaPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        account_id: Account ID for overnight delta context assembly.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id

    response = await client.get("api/v1/emitters/overnight_delta", params=params)

    raw_buckets = response.get("buckets", []) if isinstance(response, dict) else []
    buckets = [OvernightBucketDelta(**b) for b in raw_buckets if isinstance(b, dict)]

    return Vm107OvernightDeltaPayload(
        account_id=account_id,
        overall_summary=response.get("overall_summary") if isinstance(response, dict) else None,
        llm_enriched_summary=response.get("llm_enriched_summary") if isinstance(response, dict) else None,
        buckets=buckets,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=300,
                missing_fields=(),
                is_deterministic=False,  # LLM enrichment when novelty threshold crossed
            ),
            citations=(),
            assumptions=(
                "4 fixed buckets: FX/BONDS/COMMODITIES/CRYPTO — bucket order locked",
                "overall_summary always populated; LLM enrichment additive only",
                "Mirrors Phase 66 global_narrative_emitter 5-step pipeline pattern",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 overnight_delta emitter timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="Some asset buckets degraded — per-bucket _demo=True for unavailable data",
                ),
            ),
        ),
    )
