"""MentorPipelineOrchestrator — deterministic stage runner per CTX-§3 LOCKED.

Orchestrator OWNS stage transitions. Stage subordinates own cognition WITHIN stages.
Top-level profile prompt is a thin shim (CONTEXT.md §3 LOCKED).

CTX-§3 Locked execution flow:
  emit mentor_pipeline_started
    emit reader_started
    reader_output = call_subordinate(profile + "._reader", input=ReaderInput(...))
    ReaderOutput.model_validate(reader_output)   # hard-fail boundary 1
    emit reader_completed
    emit analyzer_started
    analyzer_output = call_subordinate(profile + "._analyzer", input=AnalyzerInput.from_reader(reader_output))
    AnalyzerOutput.model_validate(analyzer_output)   # hard-fail boundary 2
    emit analyzer_completed
    emit writer_started
    for attempt in range(max_writer_retries + 1):
        narrative_envelope = call_subordinate(profile + "._writer", input=WriterInput.from_analyzer(analyzer_output))
        NarrativeEnvelope.model_validate(narrative_envelope)
        if narrative_envelope.confidence_vector is not None:
            emit writer_failed; raise WriterContractError("writer attempted to supply ConfidenceVector")
        try:
            citation_validator.enforce(narrative_envelope)
            break  # GREEN
        except CitationViolation:
            if attempt == max_writer_retries:
                narrative_envelope = citation_validator.auto_bracket_unsourced(narrative_envelope)
                break  # AUTO-BRACKET path
            # else: retry inner-loop
    confidence_vector = confidence_calculator.compute(narrative_envelope, replay_metadata, regime_age_hours)
    narrative_envelope = narrative_envelope.model_copy(update={"confidence_vector": confidence_vector})
    narrative_persister_client.persist(narrative_envelope, ...)   # VM100 HTTP (Phase 39 typed-API lock)
    emit writer_completed
    emit narrative_envelope_persisted
  emit mentor_pipeline_completed
  return narrative_envelope

Locked rules:
  - Pure deterministic orchestration topology. Stage sequence is hard-coded in Python, not in LLM prompts.
  - Hard-fail boundaries: invalid ReaderOutput → analyzer never runs; invalid AnalyzerOutput → writer never runs.
  - CTX-§9 LOCKED: writer cannot supply ConfidenceVector. Orchestrator OWNS confidence computation.
  - Immutable execution context injected once at run() start; stage subordinates cannot mutate it.
  - Phase 39 typed-API lock: persist via VM100 internal HTTP endpoint, never direct DB write from VM107.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.reader_io import ReaderInput, ReaderOutput
from fingpt_core.contracts.narrative.analyzer_io import AnalyzerInput, AnalyzerOutput
from fingpt_core.contracts.narrative.writer_io import WriterInput
from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode
from helpers.citation_validator import CitationValidator, CitationViolation
from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
from helpers.scope_dispatcher import ScopeDispatcher

logger = logging.getLogger("fingpt.helpers.mentor_pipeline_orchestrator")


class MentorPipelineError(Exception):
    """Base class for orchestrator pipeline errors."""


class ReaderContractError(MentorPipelineError):
    """Raised when ReaderOutput contract validation fails (CTX-§3 hard-fail boundary 1)."""


class AnalyzerContractError(MentorPipelineError):
    """Raised when AnalyzerOutput contract validation fails (CTX-§3 hard-fail boundary 2)."""


class WriterContractError(MentorPipelineError):
    """Raised when writer output fails contract validation or violates CTX-§9."""


class MentorPipelineOrchestrator:
    """Deterministic stage runner per CTX-§3 LOCKED.

    Owns ALL stage transitions — reader → analyzer → writer → citation enforce → persist.
    Stage subordinates own cognition WITHIN their stage.

    Usage:
        orchestrator = MentorPipelineOrchestrator(
            profile="trade_auditor_agent",
            scope_dispatcher=scope_dispatcher,
            citation_validator=citation_validator,
            confidence_calculator=confidence_calculator,
            event_emitter=event_emitter,
            subordinate_invoker=subordinate_invoker,
            narrative_persister_client=narrative_persister_client,
        )
        envelope = await orchestrator.run(
            execution_id=uuid4(),
            scope_context=scope_context,
            replay_artifact_id=None,
            ruleset_version="v1.0",
            analysis_version=1,
            template_version="t1.0",
            source_snapshot_id=uuid4(),
            truth_mode=TruthMode.HISTORICAL,
        )
    """

    def __init__(
        self,
        *,
        profile: str,
        scope_dispatcher: ScopeDispatcher,
        citation_validator: CitationValidator,
        confidence_calculator: ConfidenceVectorCalculator,
        event_emitter,
        subordinate_invoker,
        narrative_persister_client,
        max_writer_retries: int = 2,
    ) -> None:
        """Inject all dependencies.

        Args:
            profile: Top-level profile name ('trade_auditor_agent' | 'behavioral_mentor_agent' | 'weekly_review_agent')
            scope_dispatcher: Signs ScopeContext JWT envelopes (CTX-§5)
            citation_validator: Enforces CTX-§4 citation rules on writer output
            confidence_calculator: Computes 5-dim ConfidenceVector per CTX-§9
            event_emitter: Phase 56 event emitter (emit() method)
            subordinate_invoker: Callable — async (profile, input) → dict
            narrative_persister_client: Async client for VM100 internal persist endpoint
            max_writer_retries: Maximum writer retry attempts on CitationViolation (default: 2)
        """
        self._profile = profile
        self._dispatcher = scope_dispatcher
        self._scope = scope_dispatcher  # backward-compat alias
        self._citation = citation_validator
        self._confidence = confidence_calculator
        self._events = event_emitter
        self._invoke = subordinate_invoker
        self._persist = narrative_persister_client
        self._max_retries = max_writer_retries

    def _prepare_scope_headers(self, scope_context: ScopeContext, correlation_id: str) -> dict:
        """Phase 60.1 (G7+G10+G22): prepare X-Agent-Scope HTTP headers from ScopeContext.

        Called at run() entry and re-used for both subordinate invocations and direct
        tool .persist() calls. Calling self._dispatcher.attach_header({}, scope_context)
        returns a fresh dict each call (non-destructive).

        If self._dispatcher is None (test mode / misconfiguration), emits
        scope_validation_failed and returns {}. The orchestrator will continue but
        downstream VM100 will reject the request — surfaces the error fast.
        """
        if self._dispatcher is None:
            self._emit(
                "scope_validation_failed",
                correlation_id,
                stage="orchestrator",
                reason="scope_dispatcher_unavailable",
            )
            return {}

        try:
            return self._dispatcher.attach_header({}, scope_context)
        except Exception as exc:
            self._emit(
                "scope_validation_failed",
                correlation_id,
                stage="orchestrator",
                reason=f"attach_header_raised: {type(exc).__name__}",
            )
            return {}

    async def run(
        self,
        *,
        execution_id: UUID | None,
        scope_context: ScopeContext,
        replay_artifact_id: UUID | None,
        ruleset_version: str,
        analysis_version: int,
        template_version: str,
        source_snapshot_id: UUID,
        truth_mode: TruthMode,
        replay_metadata: dict | None = None,
        regime_snapshot_age_hours: float = 0.0,
    ) -> NarrativeEnvelope:
        """Execute the locked stage flow per CTX-§3.

        Immutable execution context: all parameters here are captured at run() entry.
        Stage subordinates cannot mutate execution_id, scope_context, truth_mode, etc.
        They receive only what the orchestrator passes through the typed stage contracts.

        Returns:
            NarrativeEnvelope with confidence_vector injected by the orchestrator.

        Raises:
            ReaderContractError: Reader output fails Pydantic validation (hard-fail boundary 1)
            AnalyzerContractError: Analyzer output fails Pydantic validation (hard-fail boundary 2)
            WriterContractError: Writer output fails Pydantic validation or supplies ConfidenceVector (CTX-§9)
        """
        correlation_id = self._events.new_correlation_id()

        # Phase 60.1 (G7+G10+G22): prepare scope headers ONCE at run() entry.
        # Threaded into both subordinate invocations and the direct .persist() call.
        # ScopeContext is owned by the orchestrator; subordinates never sign their own scope (CTX-§5 LOCKED).
        scope_headers = self._prepare_scope_headers(scope_context, correlation_id)

        # Emit pipeline start
        self._emit("mentor_pipeline_started", correlation_id, execution_id=str(execution_id))

        # ── Stage 1: Reader ──────────────────────────────────────────────────
        self._emit("reader_started", correlation_id, execution_id=str(execution_id))
        reader_output = await self._run_reader(
            correlation_id=correlation_id,
            execution_id=execution_id,
            scope_context=scope_context,
            replay_artifact_id=replay_artifact_id,
            scope_headers=scope_headers,
        )
        self._emit("reader_completed", correlation_id, execution_id=str(execution_id))

        # ── Stage 2: Analyzer ────────────────────────────────────────────────
        self._emit("analyzer_started", correlation_id, execution_id=str(execution_id))
        analyzer_output = await self._run_analyzer(
            correlation_id=correlation_id,
            reader_output=reader_output,
            scope_headers=scope_headers,
        )
        self._emit("analyzer_completed", correlation_id, execution_id=str(execution_id))

        # ── Stage 3: Writer (with bounded retry on CitationViolation) ────────
        self._emit("writer_started", correlation_id, execution_id=str(execution_id))
        envelope = await self._run_writer(
            correlation_id=correlation_id,
            analyzer_output=analyzer_output,
            scope_headers=scope_headers,
        )

        # ── Post-writer: ConfidenceVector (CTX-§9 LOCKED: orchestrator owns this) ──
        confidence_vector = self._confidence.compute(
            envelope,
            replay_metadata or {},
            regime_snapshot_age_hours,
        )
        envelope = envelope.model_copy(update={"confidence_vector": confidence_vector})

        # ── Persist via VM100 internal endpoint (Phase 39 typed-API lock) ─────
        # Phase 60.1 (G7+G22): pass scope_headers so VM100 receives X-Agent-Scope.
        await self._persist.persist(
            envelope=envelope,
            ruleset_version=ruleset_version,
            analysis_version=analysis_version,
            template_version=template_version,
            scope_origin=scope_context.model_dump_json(),
            truth_mode=truth_mode.value,
            source_snapshot_id=source_snapshot_id,
            source_replay_artifact_id=replay_artifact_id,
            generated_by="dagster_sensor",
            generated_reason="AUTO",
            writer_profile_id=f"{self._profile}._writer",
            headers=scope_headers,
        )

        self._emit("writer_completed", correlation_id, execution_id=str(execution_id))
        self._emit("narrative_envelope_persisted", correlation_id, execution_id=str(execution_id))
        self._emit("mentor_pipeline_completed", correlation_id, execution_id=str(execution_id))

        return envelope

    # ── Private stage runners ──────────────────────────────────────────────

    async def _run_reader(
        self,
        *,
        correlation_id: str,
        execution_id: UUID | None,
        scope_context: ScopeContext,
        replay_artifact_id: UUID | None,
        scope_headers: dict,
    ) -> ReaderOutput:
        """Invoke reader sub-profile and validate output. Hard-fail boundary 1."""
        reader_input = ReaderInput(
            execution_id=execution_id,
            scope_context=scope_context,
            replay_artifact_id=replay_artifact_id,
        )
        try:
            reader_raw = await self._invoke(
                profile=f"{self._profile}._reader",
                input=reader_input,
                headers=scope_headers,
            )
            reader_output = ReaderOutput.model_validate(reader_raw)
        except Exception as exc:
            self._emit(
                "reader_failed",
                correlation_id,
                error=str(exc),
                error_code="contract_violation",
                stage="reader",
            )
            self._emit("mentor_pipeline_failed", correlation_id, stage="reader")
            raise ReaderContractError(f"reader contract violation: {exc}") from exc
        return reader_output

    async def _run_analyzer(
        self,
        *,
        correlation_id: str,
        reader_output: ReaderOutput,
        scope_headers: dict,
    ) -> AnalyzerOutput:
        """Invoke analyzer sub-profile and validate output. Hard-fail boundary 2."""
        analyzer_input = AnalyzerInput.from_reader(reader_output)
        try:
            analyzer_raw = await self._invoke(
                profile=f"{self._profile}._analyzer",
                input=analyzer_input,
                headers=scope_headers,
            )
            analyzer_output = AnalyzerOutput.model_validate(analyzer_raw)
        except Exception as exc:
            self._emit(
                "analyzer_failed",
                correlation_id,
                error=str(exc),
                error_code="contract_violation",
                stage="analyzer",
            )
            self._emit("mentor_pipeline_failed", correlation_id, stage="analyzer")
            raise AnalyzerContractError(f"analyzer contract violation: {exc}") from exc
        return analyzer_output

    async def _run_writer(
        self,
        *,
        correlation_id: str,
        analyzer_output: AnalyzerOutput,
        scope_headers: dict,
    ) -> NarrativeEnvelope:
        """Invoke writer sub-profile with bounded retry on CitationViolation.

        CTX-§9 LOCKED: writer CANNOT supply ConfidenceVector — orchestrator rejects immediately.

        After max_writer_retries exhausted with CitationViolation still firing:
          → auto_bracket_unsourced() applied; narrative persists with [UNSOURCED] markers.
        """
        writer_input = WriterInput.from_analyzer(analyzer_output)

        for attempt in range(self._max_retries + 1):
            try:
                writer_raw = await self._invoke(
                    profile=f"{self._profile}._writer",
                    input=writer_input,
                    headers=scope_headers,
                )
                envelope = NarrativeEnvelope.model_validate(writer_raw)
            except Exception as exc:
                self._emit(
                    "writer_failed",
                    correlation_id,
                    error=str(exc),
                    error_code="contract_violation",
                    attempt=attempt,
                    payload={"error": str(exc)},
                )
                self._emit("mentor_pipeline_failed", correlation_id, stage="writer")
                raise WriterContractError(f"writer contract violation: {exc}") from exc

            # CTX-§9 LOCKED: writer CANNOT supply ConfidenceVector
            if envelope.confidence_vector is not None:
                self._emit(
                    "writer_failed",
                    correlation_id,
                    reason="writer_supplied_confidence_vector",
                    attempt=attempt,
                    payload={"reason": "writer_supplied_confidence_vector"},
                )
                self._emit("mentor_pipeline_failed", correlation_id, stage="writer")
                raise WriterContractError(
                    "writer envelope must not include confidence_vector; "
                    "the orchestrator owns it (CTX-§9 LOCKED)"
                )

            # Citation enforcement — hard-fail per CTX-§4, with bounded retry
            try:
                self._citation.enforce(envelope)
                break  # green path
            except CitationViolation as cv:
                if attempt == self._max_retries:
                    # Retries exhausted — auto-bracket remaining unsourced assertions
                    envelope = self._citation.auto_bracket_unsourced(envelope)
                    self._emit(
                        "writer_unsourced_fallback",
                        correlation_id,
                        unsourced_count=envelope.unsourced_claim_count,
                        payload={"unsourced_count": envelope.unsourced_claim_count},
                    )
                    break
                # Retry — log for telemetry
                self._emit(
                    "writer_retry",
                    correlation_id,
                    attempt=attempt + 1,
                    reason=str(cv),
                    payload={"attempt": attempt + 1, "reason": str(cv)},
                )
                logger.info(
                    "Writer retry %d/%d on CitationViolation: %s",
                    attempt + 1,
                    self._max_retries,
                    cv,
                )

        return envelope

    # ── Event emission helper ──────────────────────────────────────────────

    def _emit(self, event_type: str, correlation_id: str, **payload_kwargs) -> None:
        """Emit a Phase 56 cognition lifecycle event."""
        self._events.emit(
            event_type=event_type,
            category="cognition",
            correlation_id=correlation_id,
            payload=payload_kwargs,
        )
