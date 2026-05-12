"""Tests for MentorPipelineOrchestrator — CTX-§3 + CTX-§9 LOCKED.

Covers:
  1. test_reader_contract_violation_blocks_analyzer (VALIDATION.md line 45)
  2. test_reader_failed_event_emitted (VALIDATION.md line 46)
  3. test_reader_freeform_output_blocked (VALIDATION.md line 47)
  4. test_writer_cannot_supply_confidence_vector (VALIDATION.md line 54)
  5. test_writer_retry_on_citation_violation
  6. test_auto_bracket_after_max_retries
  7. test_happy_path_event_sequence
  8. test_confidence_vector_set_by_orchestrator_not_writer
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import pytest_asyncio
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta

from fingpt_core.contracts.narrative.scope import (
    ScopeContext, AccountScope, ExecutionScope, CrossTradeVisibility,
    NarrativeVisibility, TruthMode,
)
from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.reader_io import ReaderInput, ReaderOutput
from fingpt_core.contracts.narrative.analyzer_io import AnalyzerInput, AnalyzerOutput
from fingpt_core.contracts.narrative.writer_io import WriterInput
from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
from fingpt_core.contracts.narrative.citation import CitationToken
from fingpt_core.contracts.narrative.confidence import ConfidenceVector

from helpers.citation_validator import CitationValidator, CitationViolation
from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
from helpers.mentor_pipeline_orchestrator import (
    MentorPipelineOrchestrator,
    MentorPipelineError,
    ReaderContractError,
    AnalyzerContractError,
    WriterContractError,
)


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _make_scope_context(execution_id: UUID | None = None) -> ScopeContext:
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="trade_auditor_agent",
        account_id="acc-001",
        execution_id=execution_id,
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_reader_output(execution_id: UUID | None, scope_context: ScopeContext) -> dict:
    """Return a dict that model_validate(ReaderOutput) will accept."""
    return {
        "execution_id": execution_id,
        "scope_context": scope_context.model_dump(),
        "retrieved_evidence": {"analytics": {"r_value": 2.0}},
    }


def _make_analyzer_output(execution_id: UUID | None, scope_context: ScopeContext) -> dict:
    return {
        "execution_id": execution_id,
        "scope_context": scope_context.model_dump(),
        "findings": {"r_value": 2.0},
        "cited_registry_ids": ["behavioral_analysis_tool"],
    }


def _make_cited_sentence() -> NarrativeSentence:
    """Return an ASSERTION sentence with a valid citation."""
    return NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text="The hesitation was 45 seconds [ref:behavioral_analysis_tool:hesitation_seconds].",
        citations=[
            CitationToken(registry_id="behavioral_analysis_tool", field="hesitation_seconds")
        ],
    )


def _make_uncited_sentence() -> NarrativeSentence:
    """Return an ASSERTION sentence WITHOUT citation (triggers CitationViolation)."""
    return NarrativeSentence(
        sentence_index=0,
        sentence_class=SentenceClass.ASSERTION,
        text="The hesitation was 45 seconds.",
        citations=[],
    )


def _make_writer_envelope(
    execution_id: UUID | None,
    profile: str,
    sentences: list[NarrativeSentence] | None = None,
    confidence_vector: ConfidenceVector | None = None,
) -> dict:
    """Return a writer-envelope dict. confidence_vector=None by default (correct)."""
    if sentences is None:
        sentences = [_make_cited_sentence()]
    return {
        "profile": profile,
        "execution_id": execution_id,
        "sentences": [s.model_dump() for s in sentences],
        "confidence_vector": confidence_vector.model_dump() if confidence_vector else None,
        "unsourced_claim_count": 0,
    }


def _make_confidence_vector() -> ConfidenceVector:
    return ConfidenceVector(
        citation_coverage=1.0,
        source_diversity=1,
        behavioral_evidence_density=1.0,
        replay_completeness=1.0,
        regime_data_freshness_hours=0.5,
    )


def _make_event_emitter() -> MagicMock:
    emitter = MagicMock()
    emitter.new_correlation_id.return_value = "corr-abc-123"
    return emitter


def _make_narrative_persister_client() -> MagicMock:
    client = MagicMock()
    client.persist = AsyncMock(return_value=None)
    return client


def _make_orchestrator(
    profile: str = "trade_auditor_agent",
    subordinate_invoker=None,
    event_emitter=None,
    narrative_persister_client=None,
    tmpdir: Path | None = None,
) -> MentorPipelineOrchestrator:
    """Build orchestrator with real CitationValidator + ConfidenceVectorCalculator."""
    registry_root = tmpdir or (Path(_VM107_ROOT) / "registry")
    citation_validator = CitationValidator(registry_root)
    confidence_calculator = ConfidenceVectorCalculator()

    return MentorPipelineOrchestrator(
        profile=profile,
        scope_dispatcher=MagicMock(),
        citation_validator=citation_validator,
        confidence_calculator=confidence_calculator,
        event_emitter=event_emitter or _make_event_emitter(),
        subordinate_invoker=subordinate_invoker or AsyncMock(),
        narrative_persister_client=narrative_persister_client or _make_narrative_persister_client(),
        max_writer_retries=2,
    )


# ────────────────────────────────────────────────────────────────────────────
# Helper: standard run() kwargs
# ────────────────────────────────────────────────────────────────────────────

def _run_kwargs(execution_id: UUID | None = None) -> dict:
    sc = _make_scope_context(execution_id)
    eid = execution_id or uuid4()
    return {
        "execution_id": eid,
        "scope_context": sc,
        "replay_artifact_id": None,
        "ruleset_version": "v1.0",
        "analysis_version": 1,
        "template_version": "t1.0",
        "source_snapshot_id": uuid4(),
        "truth_mode": TruthMode.HISTORICAL,
    }


# ────────────────────────────────────────────────────────────────────────────
# Test 1: VALIDATION.md line 45 — invalid ReaderOutput blocks analyzer
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reader_contract_violation_blocks_analyzer():
    """CTX-§3 — ReaderOutput validation failure raises ReaderContractError; analyzer never invoked."""
    analyzer_mock = AsyncMock()

    async def bad_reader_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return {"invalid_field": "not a valid ReaderOutput"}
        return analyzer_mock(profile=profile, input=input)

    execution_id = uuid4()
    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=bad_reader_invoker,
        event_emitter=event_emitter,
    )

    with pytest.raises(ReaderContractError):
        await orch.run(**_run_kwargs(execution_id))

    # Analyzer was never invoked
    analyzer_mock.assert_not_called()


# ────────────────────────────────────────────────────────────────────────────
# Test 2: VALIDATION.md line 46 — reader_failed event emitted on contract violation
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reader_failed_event_emitted():
    """CTX-§3 — orchestrator emits reader_failed + mentor_pipeline_failed on ReaderOutput violation."""

    async def bad_reader_invoker(profile: str, input, **kwargs):
        return {"invalid_field": "garbage"}

    execution_id = uuid4()
    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=bad_reader_invoker,
        event_emitter=event_emitter,
    )

    with pytest.raises(ReaderContractError):
        await orch.run(**_run_kwargs(execution_id))

    # Extract all event_type values from emit calls
    emitted_types = [c[1]["event_type"] for c in event_emitter.emit.call_args_list]
    assert "reader_failed" in emitted_types
    assert "mentor_pipeline_failed" in emitted_types


# ────────────────────────────────────────────────────────────────────────────
# Test 3: VALIDATION.md line 47 — freeform string output from reader is blocked
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reader_freeform_output_blocked():
    """CTX-§3 — Reader returning a plain string (LLM freeform) raises ReaderContractError."""

    async def freeform_reader_invoker(profile: str, input, **kwargs):
        return "I have analyzed the trade. The entry was well-timed."

    execution_id = uuid4()
    orch = _make_orchestrator(subordinate_invoker=freeform_reader_invoker)

    with pytest.raises(ReaderContractError):
        await orch.run(**_run_kwargs(execution_id))


# ────────────────────────────────────────────────────────────────────────────
# Test 4: VALIDATION.md line 54 — writer cannot supply ConfidenceVector
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_writer_cannot_supply_confidence_vector():
    """CTX-§9 — Writer supplying ConfidenceVector causes WriterContractError."""
    execution_id = uuid4()
    scope_context = _make_scope_context(execution_id)

    async def sneaky_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return _make_reader_output(execution_id, scope_context)
        if "_analyzer" in profile:
            return _make_analyzer_output(execution_id, scope_context)
        # _writer: supplies ConfidenceVector (violation!)
        return _make_writer_envelope(
            execution_id=execution_id,
            profile="trade_auditor_agent",
            sentences=[_make_cited_sentence()],
            confidence_vector=_make_confidence_vector(),
        )

    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=sneaky_invoker,
        event_emitter=event_emitter,
    )

    with pytest.raises(WriterContractError, match="confidence_vector"):
        await orch.run(**_run_kwargs(execution_id))

    # writer_failed event must be emitted with reason="writer_supplied_confidence_vector"
    writer_failed_calls = [
        c for c in event_emitter.emit.call_args_list
        if c[1].get("event_type") == "writer_failed"
    ]
    assert writer_failed_calls, "writer_failed event must be emitted"
    # The payload should contain reason="writer_supplied_confidence_vector"
    payload_reasons = [
        c[1].get("payload", {}).get("reason") for c in writer_failed_calls
    ]
    assert "writer_supplied_confidence_vector" in payload_reasons


# ────────────────────────────────────────────────────────────────────────────
# Test 5: writer retries on citation violation (2x then succeeds 3rd)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_writer_retry_on_citation_violation(tmp_path):
    """Orchestrator retries writer up to 2x on CitationViolation; succeeds on 3rd attempt."""
    execution_id = uuid4()
    scope_context = _make_scope_context(execution_id)

    # Use a tmpdir registry — no known registry IDs, so we must use uncited sentences to trigger violation.
    # But wait: if registry is empty, unknown IDs also fail. Let's use an uncited assertion
    # (no citations = violation regardless of registry).
    call_count = [0]

    async def retry_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return _make_reader_output(execution_id, scope_context)
        if "_analyzer" in profile:
            return _make_analyzer_output(execution_id, scope_context)
        # _writer: first 2 times uncited, 3rd time cited (but empty registry, so need no citations check)
        call_count[0] += 1
        if call_count[0] < 3:
            # Return uncited ASSERTION (violates rule 1: ASSERTION without citation)
            return _make_writer_envelope(
                execution_id=execution_id,
                profile="trade_auditor_agent",
                sentences=[_make_uncited_sentence()],
            )
        # 3rd call: TRANSITION sentence (no citation required)
        return _make_writer_envelope(
            execution_id=execution_id,
            profile="trade_auditor_agent",
            sentences=[
                NarrativeSentence(
                    sentence_index=0,
                    sentence_class=SentenceClass.TRANSITION,
                    text="Overall the trade was well managed.",
                    citations=[],
                )
            ],
        )

    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=retry_invoker,
        event_emitter=event_emitter,
        tmpdir=tmp_path,
    )

    envelope = await orch.run(**_run_kwargs(execution_id))
    assert envelope is not None
    assert call_count[0] == 3

    # No auto-bracket — should not have been fired (succeeded on 3rd attempt)
    emitted_types = [c[1]["event_type"] for c in event_emitter.emit.call_args_list]
    assert "writer_unsourced_fallback" not in emitted_types


# ────────────────────────────────────────────────────────────────────────────
# Test 6: auto_bracket fires after max_writer_retries exhausted
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_bracket_after_max_retries(tmp_path):
    """After 2 retries still CitationViolation → auto_bracket; unsourced_claim_count > 0."""
    execution_id = uuid4()
    scope_context = _make_scope_context(execution_id)

    async def always_uncited_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return _make_reader_output(execution_id, scope_context)
        if "_analyzer" in profile:
            return _make_analyzer_output(execution_id, scope_context)
        return _make_writer_envelope(
            execution_id=execution_id,
            profile="trade_auditor_agent",
            sentences=[_make_uncited_sentence()],
        )

    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=always_uncited_invoker,
        event_emitter=event_emitter,
        tmpdir=tmp_path,
    )

    envelope = await orch.run(**_run_kwargs(execution_id))

    # Auto-bracket was applied → unsourced_claim_count incremented
    assert envelope.unsourced_claim_count > 0

    # writer_unsourced_fallback event emitted
    emitted_types = [c[1]["event_type"] for c in event_emitter.emit.call_args_list]
    assert "writer_unsourced_fallback" in emitted_types


# ────────────────────────────────────────────────────────────────────────────
# Test 7: happy path — event sequence matches locked flow
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_event_sequence(tmp_path):
    """Verify the locked event sequence per CTX-§3."""
    execution_id = uuid4()
    scope_context = _make_scope_context(execution_id)

    async def happy_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return _make_reader_output(execution_id, scope_context)
        if "_analyzer" in profile:
            return _make_analyzer_output(execution_id, scope_context)
        return _make_writer_envelope(
            execution_id=execution_id,
            profile="trade_auditor_agent",
            sentences=[
                NarrativeSentence(
                    sentence_index=0,
                    sentence_class=SentenceClass.TRANSITION,
                    text="The trade execution was smooth.",
                    citations=[],
                )
            ],
        )

    event_emitter = _make_event_emitter()
    orch = _make_orchestrator(
        subordinate_invoker=happy_invoker,
        event_emitter=event_emitter,
        tmpdir=tmp_path,
    )

    await orch.run(**_run_kwargs(execution_id))

    emitted_types = [c[1]["event_type"] for c in event_emitter.emit.call_args_list]

    # Must appear (in order)
    required_events = [
        "mentor_pipeline_started",
        "reader_started",
        "reader_completed",
        "analyzer_started",
        "analyzer_completed",
        "writer_started",
        "writer_completed",
        "mentor_pipeline_completed",
    ]
    for evt in required_events:
        assert evt in emitted_types, f"Expected event '{evt}' not emitted. Got: {emitted_types}"

    # Verify ordering: mentor_pipeline_started must come before all others
    assert emitted_types.index("mentor_pipeline_started") < emitted_types.index("reader_started")
    assert emitted_types.index("reader_completed") < emitted_types.index("analyzer_started")
    assert emitted_types.index("analyzer_completed") < emitted_types.index("writer_started")
    assert emitted_types.index("writer_completed") < emitted_types.index("mentor_pipeline_completed")


# ────────────────────────────────────────────────────────────────────────────
# Test 8: confidence_vector set by orchestrator, not writer
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confidence_vector_set_by_orchestrator_not_writer(tmp_path):
    """Writer returns envelope with confidence_vector=None; orchestrator injects ConfidenceVector."""
    execution_id = uuid4()
    scope_context = _make_scope_context(execution_id)

    async def clean_invoker(profile: str, input, **kwargs):
        if "_reader" in profile:
            return _make_reader_output(execution_id, scope_context)
        if "_analyzer" in profile:
            return _make_analyzer_output(execution_id, scope_context)
        return _make_writer_envelope(
            execution_id=execution_id,
            profile="trade_auditor_agent",
            sentences=[
                NarrativeSentence(
                    sentence_index=0,
                    sentence_class=SentenceClass.TRANSITION,
                    text="Trade was well managed.",
                    citations=[],
                )
            ],
            confidence_vector=None,  # correct — writer does NOT supply this
        )

    orch = _make_orchestrator(
        subordinate_invoker=clean_invoker,
        tmpdir=tmp_path,
    )

    envelope = await orch.run(**_run_kwargs(execution_id))

    # Orchestrator MUST have injected the ConfidenceVector
    assert envelope.confidence_vector is not None
    assert isinstance(envelope.confidence_vector, ConfidenceVector)
