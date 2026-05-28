"""Phase 70.5 Decision 18 — proxy for vm107.reflection_prompt.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM107's own reflection prompt emitter endpoint, returns a typed
ToolPayload, and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM107 reflection_prompt emitter exists (Phase 67).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient


class EvidenceChainItem(BaseModel):
    """Structured evidence chain item per RESEARCH recommendation."""

    model_config = ConfigDict(extra="allow")

    kind: str  # trade / event / pattern / session
    ref: str   # opaque reference ID
    weight: float | None = None


class ReflectionPromptItem(BaseModel):
    """A single selected reflection prompt."""

    model_config = ConfigDict(extra="allow")

    prompt_id: str | None = None
    prompt_text: str | None = None
    deterministic_prompt: str | None = None
    llm_enriched: bool = False
    evidence_chain: list[EvidenceChainItem] = Field(default_factory=list)
    score: float | None = None


class Vm107ReflectionPromptPayload(BaseModel):
    """Typed payload for vm107.reflection_prompt proxy.

    CLOSE-state 4 reflection prompts assembled via 5-stage progressive enrichment:
    deterministic candidate scoring → multi-domain evidence convergence eligibility →
    score-then-diversify hybrid selection → coherence pass → optional LLM enrichment.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    account_id: int | None = None
    selected_prompts: list[ReflectionPromptItem] = Field(default_factory=list)
    rejected_count: int = 0  # rejected candidates persisted for Phase 62 tuning
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    **kwargs,
) -> Vm107ReflectionPromptPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        account_id: Account ID for reflection prompt assembly.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id

    response = await client.get("api/v1/emitters/reflection_prompts", params=params)

    raw_prompts = response.get("selected_prompts", []) if isinstance(response, dict) else []
    prompts = [ReflectionPromptItem(**p) for p in raw_prompts if isinstance(p, dict)]
    rejected_count = response.get("rejected_count", 0) if isinstance(response, dict) else 0

    return Vm107ReflectionPromptPayload(
        account_id=account_id,
        selected_prompts=prompts,
        rejected_count=rejected_count,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if prompts else "sparse",
                freshness_observed_seconds=300,
                missing_fields=() if prompts else ("selected_prompts",),
                is_deterministic=False,  # LLM enrichment gated by NoveltyEngine
            ),
            citations=(),
            assumptions=(
                "CLOSE-state only — 4 prompts per session via 5-stage pipeline",
                "LLM enrichment is ADDITIVE ONLY — never replaces deterministic prompt",
                "Rejected candidates persisted for Phase 62 tuning",
                "evidence_chain uses structured {kind, ref, weight} per RESEARCH recommendation",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 reflection_prompts emitter timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No reflection prompts assembled — insufficient session evidence",
                ),
            ),
        ),
    )
