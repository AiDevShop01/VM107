"""Phase 70.5 Plan 03 — universal tool invocation boundary (Decision 8 + 16).

The dispatcher is the SOLE surface that may invoke a capability AND the SOLE
envelope construction site. Every tool call flows through dispatch_tool().
Every path returns a ToolResultEnvelope — never a bare dict.

Phase 47.6 LD-6c invariants preserved:
- dispatch_tool() writes CapabilityRefusalEvent to envelope.capability_refusal_log
  on stub/experimental refusal AND on confidence-refusal (Pitfall 8).
- The refusal cascade reads from capability_refusal_log ONLY (never introspection_log).

Public API:
    dispatch_tool(tool_id, kwargs, ctx) -> ToolResultEnvelope   (async, Decision 16)
    wrap_in_envelope(tool_id, payload, signals, outcome_class, failure_modes, ctx, entry)
        -> ToolResultEnvelope                                    (thin public facade)
    class UnknownToolError(Exception)                           (preserved for callers)

Internal helpers (all private, beginning with _):
    _get_registry()                              — patchable in tests
    _get_tool_entry(tool_id)                     — patchable in tests
    _lookup_summary(tool_id)                     — patchable in tests
    _invoke_resolver(tool_id, kwargs, child_ctx) — patchable in tests (async)
    _derive_child_ctx(ctx, new_envelope_id)      — produces InvocationContext depth+1
    _build_refused_envelope(...)                 — refused outcome on every refusal path
    _build_failure_envelope(...)                 — failure outcome on exception paths
    _build_success_envelope(...)                 — success/partial/degraded outcome

Confidence-refusal rule (REQ-70.5-5):
    If compute_confidence() returns a value < CONFIDENCE_REFUSAL_THRESHOLD (0.3),
    the outcome_class is flipped from "success" to "refused" and a
    CapabilityRefusalEvent is appended to the agent envelope (Pitfall 8 cascade).

Recursion guard:
    ctx.execution_depth > MAX_EXECUTION_DEPTH (8) → immediate refused envelope,
    BEFORE any registry lookup or resolver call.

Exception → FailureModeCode mapping:
    TimeoutError         → UPSTREAM_TIMEOUT
    PermissionError      → PERMISSION_DENIED
    KeyError, IndexError → NO_MATCH_FOUND
    Exception (default)  → INSUFFICIENT_CONTEXT
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.capability_registry import CapabilityRefusalEvent
from fingpt_core.contracts.confidence_calculator import compute_confidence
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import (
    MAX_EXECUTION_DEPTH,
    InvocationContext,
)
from fingpt_core.contracts.tool_envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ToolResultEnvelope,
)

from core.agents.envelope_context import current_envelope
from core.agents.envelope_telemetry import emit_envelope_log
from core.agents.refusal_cascade import (
    IMPACT_TO_CONFIDENCE_DELTA,
    build_refusal_payload,
    should_refuse,
)
from core.registry.capability_registry import CapabilityRegistry

# Confidence threshold below which outcome_class is flipped to "refused"
CONFIDENCE_REFUSAL_THRESHOLD: float = 0.3


class UnknownToolError(Exception):
    """Raised when dispatch_tool() cannot find the requested tool in the registry."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Unknown tool: {tool_name!r} — not registered in capability registry"
        )
        self.tool_name = tool_name


# ---------------------------------------------------------------------------
# Inline RefusalPayload (plan recommendation: keep inline to avoid bloating fingpt_core)
# ---------------------------------------------------------------------------


class RefusalPayload(BaseModel):
    """Minimal frozen payload for refused envelopes (both stub/experimental and confidence)."""

    model_config = ConfigDict(frozen=True)

    reason: str
    PAYLOAD_SCHEMA_VERSION: str = "1.0"


# ---------------------------------------------------------------------------
# Patchable internal accessors (tests override these to inject mock objects)
# ---------------------------------------------------------------------------


def _get_registry() -> CapabilityRegistry:
    """Return the active CapabilityRegistry singleton. Patchable in tests."""
    return CapabilityRegistry.get()


def _get_tool_entry(tool_id: str):
    """Return ToolEntry for tool_id (raises KeyError if not found). Patchable in tests."""
    from core.agents.tool_registry import get_tool_entry
    return get_tool_entry(tool_id)


def _lookup_summary(tool_id: str):
    """Lookup CapabilitySummary by id. Patchable in tests for refusal path."""
    reg = _get_registry()
    return reg.lookup(tool_id)


async def _invoke_resolver(tool_id: str, kwargs: dict, ctx: InvocationContext) -> Any:
    """Invoke the tool via the Plan 02 resolver. Patchable in tests."""
    from core.agents.tool_resolver import invoke
    return await invoke(tool_id, kwargs, ctx)


# ---------------------------------------------------------------------------
# Context derivation
# ---------------------------------------------------------------------------


def _derive_child_ctx(ctx: InvocationContext, new_envelope_id: uuid.UUID) -> InvocationContext:
    """Derive a child InvocationContext for nested dispatch.

    Same trace_id and agent_id. parent_envelope_id = caller's envelope_id.
    execution_depth += 1.
    """
    return InvocationContext(
        envelope_id=new_envelope_id,
        parent_envelope_id=ctx.envelope_id,
        trace_id=ctx.trace_id,
        agent_id=ctx.agent_id,
        conversation_id=ctx.conversation_id,
        execution_depth=ctx.execution_depth + 1,
    )


# ---------------------------------------------------------------------------
# Envelope builders (private)
# ---------------------------------------------------------------------------


def _build_refused_envelope(
    tool_id: str,
    ctx: InvocationContext,
    *,
    reason: str,
    summary: Any = None,
    entry: Any = None,
) -> ToolResultEnvelope:
    """Build a refused ToolResultEnvelope.

    Used for:
    - Recursion guard fires
    - Stub / experimental refusal (Phase 47.6 LD-6c)
    - Confidence < CONFIDENCE_REFUSAL_THRESHOLD flip (REQ-70.5-5)

    Preserves Phase 47.6 CapabilityRefusalEvent write to current_envelope.
    The caller is responsible for writing the event BEFORE calling this builder
    when a summary is available (stub/experimental path) — or this builder writes
    it when called from the confidence-refusal path.
    """
    reg = _get_registry()
    snapshot_hash = reg.snapshot_hash

    version = getattr(entry, "version", None) or "1.0"

    payload = RefusalPayload(reason=reason)

    envelope = ToolResultEnvelope[RefusalPayload](
        envelope_id=ctx.envelope_id,
        parent_envelope_id=ctx.parent_envelope_id,
        tool_name=tool_id,
        tool_version=version,
        outcome_class="refused",
        success=False,
        refusal_reason=reason,
        generated_at=datetime.now(timezone.utc),
        confidence=None,
        confidence_reasoning=(),
        citations=(),
        assumptions=(),
        failure_modes=(),
        normalization_warnings=(),
        registry_snapshot_hash=snapshot_hash,
        envelope_schema_version=ENVELOPE_SCHEMA_VERSION,
        payload_schema_version="1.0",
        payload=payload,
    )

    emit_envelope_log(envelope, ctx)
    return envelope


def _build_failure_envelope(
    tool_id: str,
    exc: Exception,
    ctx: InvocationContext,
    entry: Any,
) -> ToolResultEnvelope:
    """Build a failure ToolResultEnvelope from a resolver exception.

    Exception → FailureModeCode mapping (Decision 6 + plan spec):
        TimeoutError         → UPSTREAM_TIMEOUT
        PermissionError      → PERMISSION_DENIED
        KeyError, IndexError → NO_MATCH_FOUND
        else                 → INSUFFICIENT_CONTEXT
    """
    _EXC_TO_CODE: dict[type, FailureModeCode] = {
        TimeoutError: FailureModeCode.UPSTREAM_TIMEOUT,
        PermissionError: FailureModeCode.PERMISSION_DENIED,
        KeyError: FailureModeCode.NO_MATCH_FOUND,
        IndexError: FailureModeCode.NO_MATCH_FOUND,
    }
    code = _EXC_TO_CODE.get(type(exc), FailureModeCode.INSUFFICIENT_CONTEXT)
    failure_mode = FailureMode(code=code, detail=str(exc) or repr(exc))

    reg = _get_registry()
    snapshot_hash = reg.snapshot_hash
    version = getattr(entry, "version", None) or "1.0"

    payload = RefusalPayload(reason=f"tool_exception:{type(exc).__name__}")

    envelope = ToolResultEnvelope[RefusalPayload](
        envelope_id=ctx.envelope_id,
        parent_envelope_id=ctx.parent_envelope_id,
        tool_name=tool_id,
        tool_version=version,
        outcome_class="failure",
        success=False,
        refusal_reason=None,
        generated_at=datetime.now(timezone.utc),
        confidence=None,
        confidence_reasoning=(),
        citations=(),
        assumptions=(),
        failure_modes=(failure_mode,),
        normalization_warnings=(),
        registry_snapshot_hash=snapshot_hash,
        envelope_schema_version=ENVELOPE_SCHEMA_VERSION,
        payload_schema_version="1.0",
        payload=payload,
    )

    emit_envelope_log(envelope, ctx)
    return envelope


def _build_success_envelope(
    tool_id: str,
    payload: Any,
    signals_override: Any,
    ctx: InvocationContext,
    entry: Any,
    runtime_failure_modes: tuple = (),
) -> ToolResultEnvelope:
    """Build a success/partial/degraded/refused ToolResultEnvelope.

    Extracts provenance from payload.provenance when present (Decision 5 + Pitfall 9).
    Runs compute_confidence() — if result < CONFIDENCE_REFUSAL_THRESHOLD, flips to
    refused and writes CapabilityRefusalEvent cascade (Pitfall 8, REQ-70.5-5).

    Args:
        tool_id: Registry capability id.
        payload: Typed tool payload (may have a .provenance: ToolProvenance field).
        signals_override: ToolConfidenceSignals to use instead of payload.provenance.signals.
        ctx: InvocationContext for this dispatch.
        entry: ToolEntry from the registry (typical_confidence, expected_freshness_seconds, etc.)
        runtime_failure_modes: Additional failure modes from the dispatcher itself (default empty).
    """
    reg = _get_registry()
    snapshot_hash = reg.snapshot_hash

    # --- Provenance extraction (Decision 5 + Pitfall 9) ---
    provenance = getattr(payload, "provenance", None)
    if provenance is not None:
        citations = provenance.citations
        assumptions = provenance.assumptions
        declared_failure_modes = provenance.declared_failure_modes
        # signals: use explicit override first, else payload.provenance.signals
        signals = signals_override
        if signals is None and provenance.signals is not None:
            signals = provenance.signals
    else:
        citations = ()
        assumptions = ()
        declared_failure_modes = ()
        signals = signals_override

    # Merge declared + runtime failure modes
    all_failure_modes = tuple(declared_failure_modes) + tuple(runtime_failure_modes)

    # --- Confidence computation (Decision 2) ---
    baseline = getattr(entry, "typical_confidence", None)
    expected_freshness = getattr(entry, "expected_freshness_seconds", None)
    entry_is_deterministic = getattr(entry, "is_deterministic", None)

    if signals is not None:
        # Tool MAY override is_deterministic (e.g. detected runtime non-determinism)
        is_det = signals.is_deterministic if signals.is_deterministic is not None else entry_is_deterministic
        evidence_quality = signals.evidence_quality
        freshness_observed = signals.freshness_observed_seconds
        missing_count = len(signals.missing_fields)
    else:
        is_det = entry_is_deterministic
        evidence_quality = None
        freshness_observed = None
        missing_count = 0

    confidence, confidence_reasoning = compute_confidence(
        baseline=baseline,
        is_deterministic=is_det,
        evidence_quality=evidence_quality,
        freshness_observed_seconds=freshness_observed,
        expected_freshness_seconds=expected_freshness,
        missing_field_count=missing_count,
        outcome_class="success",  # pre-flip outcome; compute_confidence returns None for failure/refused
    )

    # --- Confidence-refusal flip (REQ-70.5-5) ---
    if confidence is not None and confidence < CONFIDENCE_REFUSAL_THRESHOLD:
        # Write CapabilityRefusalEvent cascade (Pitfall 8 — same Phase 47.6 cascade path).
        # registry_status is set to "experimental" to satisfy the schema literal constraint
        # (CapabilityRefusalEvent only accepts "stub"|"experimental"; confidence-below-threshold
        # invocations are epistemically "experimental" — we refuse them at the trust boundary).
        agent_envelope = current_envelope.get()
        if agent_envelope is not None:
            event = CapabilityRefusalEvent(
                capability_id=tool_id,
                registry_status="experimental",
                impact_on_decision="MEDIUM",
                planned_phase=None,
                impact_on_reasoning="low_confidence_refusal",
                auto_confidence_adjustment=IMPACT_TO_CONFIDENCE_DELTA.get("MEDIUM", -10),
                registry_snapshot_hash=snapshot_hash,
                occurred_at=datetime.now(timezone.utc),
                reasoning_context_id=str(getattr(agent_envelope, "envelope_id", "unknown") or "unknown"),
            )
            agent_envelope.capability_refusal_log.append(event)

        reason = f"confidence_below_threshold:{confidence:.2f}"
        return _build_refused_envelope(
            tool_id=tool_id,
            ctx=ctx,
            reason=reason,
            entry=entry,
        )

    # --- Versioning ---
    version = getattr(entry, "version", None) or "1.0"
    payload_schema_version = getattr(payload, "PAYLOAD_SCHEMA_VERSION", "1.0")

    # --- Freshness computation ---
    # freshness_seconds = signals.freshness_observed_seconds (proxy for now;
    # full source_generated_at tracking deferred to Plan 06 pilot RICH wrappers)
    freshness_seconds = freshness_observed

    # --- outcome_class derivation ---
    # "success" if no declared/runtime failure modes and confidence is high
    # "degraded" if confidence is lower than baseline (evidence quality / freshness penalty)
    # "partial"  if runtime_failure_modes present (tool ran but some sub-results unavailable)
    # For simplicity in Plan 03 scope: success unless failure_modes present
    if all_failure_modes:
        outcome_class = "partial"
    else:
        outcome_class = "success"

    envelope = ToolResultEnvelope(
        envelope_id=ctx.envelope_id,
        parent_envelope_id=ctx.parent_envelope_id,
        tool_name=tool_id,
        tool_version=version,
        outcome_class=outcome_class,
        success=outcome_class not in ("failure", "refused"),
        refusal_reason=None,
        generated_at=datetime.now(timezone.utc),
        source_generated_at=None,
        observed_at=None,
        event_occurred_at=None,
        freshness_seconds=freshness_seconds,
        confidence=confidence,
        confidence_reasoning=confidence_reasoning,
        citations=citations,
        assumptions=assumptions,
        failure_modes=all_failure_modes,
        normalization_warnings=(),
        registry_snapshot_hash=snapshot_hash,
        envelope_schema_version=ENVELOPE_SCHEMA_VERSION,
        payload_schema_version=payload_schema_version,
        payload=payload,
    )

    emit_envelope_log(envelope, ctx)
    return envelope


# ---------------------------------------------------------------------------
# Public facade: wrap_in_envelope
# ---------------------------------------------------------------------------


def wrap_in_envelope(
    tool_id: str,
    payload: Any,
    signals: Any,
    outcome_class: str,
    failure_modes: tuple,
    ctx: InvocationContext,
    entry: Any,
) -> ToolResultEnvelope:
    """Public facade over _build_success_envelope — the canonical provenance-extraction entry.

    Callers may pass payload with a populated ``provenance: ToolProvenance`` field
    and the dispatcher will extract ``citations`` / ``assumptions`` / ``declared_failure_modes``
    onto the envelope automatically.

    Plan 06 pilot RICH wrappers populate ``payload.provenance`` and call ``dispatch_tool``
    directly — they do NOT need to pass citations/assumptions separately. Plan 07 proxies
    follow the same pattern.

    Args:
        tool_id: Registry capability id.
        payload: Typed tool payload (may carry ToolProvenance).
        signals: ToolConfidenceSignals override (or None to use payload.provenance.signals).
        outcome_class: The desired outcome class (used for context; actual derivation is internal).
        failure_modes: Runtime failure modes tuple (merged with declared ones from provenance).
        ctx: InvocationContext for lineage threading.
        entry: ToolEntry from tool_registry.

    Returns:
        Frozen ToolResultEnvelope with provenance extracted, confidence computed,
        and telemetry emitted.
    """
    return _build_success_envelope(
        tool_id=tool_id,
        payload=payload,
        signals_override=signals,
        ctx=ctx,
        entry=entry,
        runtime_failure_modes=failure_modes,
    )


# ---------------------------------------------------------------------------
# Primary dispatch entry point
# ---------------------------------------------------------------------------


async def dispatch_tool(
    tool_id: str,
    kwargs: dict,
    ctx: InvocationContext,
) -> ToolResultEnvelope:
    """Universal async tool invocation boundary (Decision 8 + 16 + 19).

    This is the SOLE invocation site for all capabilities. Every tool call
    from the agent runtime and from tool-to-tool calls flows through here.

    Flow:
      1. Recursion guard — refuse immediately if ctx.execution_depth > MAX_EXECUTION_DEPTH
      2. Registry lookup — UnknownToolError if not found
      3. Stub/experimental refusal — writes CapabilityRefusalEvent, returns refused envelope
      4. Invoke resolver — catches CapabilityRefusedError and all other exceptions
      5. wrap_in_envelope (via _build_success_envelope) — extracts provenance, computes
         confidence, flips to refused if < 0.3, writes cascade if so
      6. Emit telemetry (inside builders — every path)
      7. Return envelope

    Args:
        tool_id: Registry capability id (must match CapabilityRegistry entry id exactly).
        kwargs: Tool keyword arguments spread to the callable as **kwargs.
        ctx: InvocationContext — carries trace_id, envelope_id, parent, depth.

    Returns:
        ToolResultEnvelope on EVERY code path — never raises for tool-level errors.

    Raises:
        UnknownToolError: If tool_id is not registered.
    """
    # --- Step 1: Recursion guard ---
    if ctx.execution_depth > MAX_EXECUTION_DEPTH:
        return _build_refused_envelope(
            tool_id=tool_id,
            ctx=ctx,
            reason="recursion_depth_exceeded",
        )

    # --- Step 2: Registry lookup (UnknownToolError if not found) ---
    try:
        entry = _get_tool_entry(tool_id)
    except KeyError as exc:
        raise UnknownToolError(tool_id) from exc

    summary = _lookup_summary(tool_id)

    # --- Step 3: Stub/experimental refusal ---
    if summary is not None and should_refuse(summary):
        # LD-6c: write CapabilityRefusalEvent to the active agent envelope
        agent_envelope = current_envelope.get()
        if agent_envelope is not None:
            event = CapabilityRefusalEvent(
                capability_id=summary.id,
                registry_status=summary.status.value,
                impact_on_decision=summary.impact_on_decision.value,
                planned_phase=summary.location.get("planned_phase"),
                impact_on_reasoning="partial_context_loss",
                auto_confidence_adjustment=IMPACT_TO_CONFIDENCE_DELTA[
                    summary.impact_on_decision.value
                ],
                registry_snapshot_hash=_get_registry().snapshot_hash,
                occurred_at=datetime.now(timezone.utc),
                reasoning_context_id=str(
                    getattr(agent_envelope, "envelope_id", "unknown") or "unknown"
                ),
            )
            agent_envelope.capability_refusal_log.append(event)

        reason = f"capability_unavailable:{summary.status.value}"
        return _build_refused_envelope(
            tool_id=tool_id,
            ctx=ctx,
            reason=reason,
            summary=summary,
            entry=entry,
        )

    # --- Step 4: Invoke resolver ---
    # Derive a child context for nested dispatch lineage
    child_ctx = _derive_child_ctx(ctx, new_envelope_id=uuid.uuid4())

    try:
        from core.agents.tool_resolver import CapabilityRefusedError
        try:
            payload = await _invoke_resolver(tool_id, kwargs, child_ctx)
        except CapabilityRefusedError as exc:
            # Resolver-level refusal (e.g. facade not yet implemented)
            return _build_refused_envelope(
                tool_id=tool_id,
                ctx=ctx,
                reason=f"capability_unavailable:{exc.reason}",
                entry=entry,
            )
    except Exception as exc:
        # Generic exception → failure envelope
        return _build_failure_envelope(
            tool_id=tool_id,
            exc=exc,
            ctx=ctx,
            entry=entry,
        )

    # --- Step 5–6: wrap in envelope (confidence, provenance, telemetry) ---
    return _build_success_envelope(
        tool_id=tool_id,
        payload=payload,
        signals_override=None,  # Plan 06 RICH wrappers populate payload.provenance.signals
        ctx=ctx,
        entry=entry,
    )
