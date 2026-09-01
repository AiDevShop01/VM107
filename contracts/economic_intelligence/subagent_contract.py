"""AZE-07 — Subagent request/result envelope + closed StopReason union.

Phase 155 (router→specialist fan-out executor). The net-new structured contract the
``MacroAskExecutor`` wraps every in-process specialist dispatch in so a fan-out that
partially fails degrades *honestly* (a non-``completed`` section, never a fabricated
answer) and an unknown/out-of-scope routed id fails *loud* (``stop_reason="error"``
naming the id) instead of being accept-then-silently-dropped.

Shapes mirror ``contracts.economic_intelligence.specialist_response`` (frozen +
``extra="forbid"`` pydantic) — the same rigor the synthesizer already trusts.

Fields carried but moot in-process this phase (D-02): ``output_schema`` names the trusted
return schema (``SpecialistResponse``) as a reference, and ``tool_filter`` carries the
specialist's ``allowed_tools``/``denied_tools`` from ``registry/agent_profile/*.yaml`` so
Phase 157 wires ``_05_tool_scope_filter`` without re-plumbing the envelope.

SECURITY (T-155-01): ``diagnostic`` MUST NEVER contain the ``VM107_SERVICE_JWT`` (or any
bearer/secret). It carries exception type / agent id / elapsed only — never a raw payload
or auth header.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.economic_intelligence.specialist_response import SpecialistResponse

# Closed union — exactly these five members, no more, no less (AZE-07). A string outside
# this set is rejected at construction so the coordinator can branch exhaustively.
StopReason = Literal["completed", "aborted", "error", "max_tokens", "refusal"]


class SubagentRequest(BaseModel):
    """The structured request the executor builds per specialist before dispatch.

    ``tool_filter`` and ``output_schema`` are carried-but-moot in the in-process path
    this phase (D-02); they exist so the Phase-157 sub-agent-dispatch upgrade wires tool
    scoping / schema enforcement without changing this envelope.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1)
    output_schema: str = Field(
        description="Name of the trusted return schema (e.g. 'SpecialistResponse') — a "
        "reference the executor validates against, NOT a re-parsed model.",
    )
    tool_filter: dict[str, Any] = Field(
        description="The specialist's allowed_tools/denied_tools carried from its "
        "agent_profile (moot in-process this phase; Phase-157 enforcement input).",
    )
    persona: str = Field(
        min_length=1,
        description="The specialist agent_id (dotted, e.g. 'vm107.inflation_analyst').",
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        description="Sub-dispatch recursion ceiling (matches profile max_iterations: 1).",
    )


class SubagentResult(BaseModel):
    """The structured result of a single specialist dispatch.

    A non-``completed`` ``stop_reason`` marks a degraded/errored section: ``structured``
    is ``None`` (or a confidence=0.0 sentinel supplied by the executor) — the coordinator
    surfaces it under ``limitations`` and NEVER presents it as a real answer (T-155-09).

    SECURITY: ``diagnostic`` MUST NEVER carry the JWT or any secret (T-155-01).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: str = Field(
        description="The specialist's human-readable answer text (or a degraded sentinel).",
    )
    structured: SpecialistResponse | dict[str, Any] | None = Field(
        default=None,
        description="The typed SpecialistResponse on success; None (or a 0.0 sentinel) "
        "for a degraded/errored section.",
    )
    stop_reason: StopReason = Field(
        description="Closed union — the coordinator branches on this exhaustively.",
    )
    diagnostic: dict[str, Any] | str = Field(
        default="",
        description="JWT-FREE trace context (exception type / id / elapsed). "
        "MUST NEVER contain the bearer token or a raw payload.",
    )
