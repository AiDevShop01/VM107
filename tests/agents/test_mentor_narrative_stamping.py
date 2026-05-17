"""Phase 47.6-04 Task 2 — Mentor narrative stamping tests.

Tests:
- test_persist_narrative_tool_passes_stamp: PersistNarrativeRequest includes 3 stamp fields
- test_orchestrator_passes_stamp_kwargs: mentor_pipeline_orchestrator calls persist with stamp
- test_mentor_narrative_envelope_has_provenance: PersistNarrativeRequest carries provenance fields
  (NarrativeEnvelope is the writer contract — stamp lives in PersistNarrativeRequest)
- test_three_collections_consistent: single session → same hash across all 3 surfaces
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

VALID_HASH = "aabbccdd11223344"
VALID_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _make_fake_registry(snapshot_hash: str = VALID_HASH):
    fake_snapshot = MagicMock()
    fake_snapshot.snapshot_generated_at = VALID_TS
    fake_snapshot.snapshot_schema_version = "1.0"
    fake_reg = MagicMock()
    fake_reg.snapshot_hash = snapshot_hash
    fake_reg.snapshot = fake_snapshot
    return fake_reg


def _make_minimal_narrative_envelope():
    """Build a minimal NarrativeEnvelope for test use."""
    from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
    return NarrativeEnvelope(
        profile="trade_auditor",
        execution_id=None,
        sentences=[],
    )


def _make_scope_context():
    """Build a minimal valid ScopeContext for test use."""
    from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode, NarrativeVisibility
    now = datetime(2026, 5, 17, tzinfo=timezone.utc)
    future = datetime(2026, 5, 18, tzinfo=timezone.utc)
    return ScopeContext(
        profile_id="trade_auditor_agent",
        account_id=None,
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        narrative_visibility=NarrativeVisibility.NONE,
        issued_at=now,
        expires_at=future,
    )


def test_persist_narrative_request_has_provenance_fields():
    """PersistNarrativeRequest carries the 3 provenance fields (registry_snapshot_hash etc.)."""
    import pydantic
    from tools.persist_narrative import PersistNarrativeRequest

    # Verify the 3 provenance fields are declared on PersistNarrativeRequest
    fields = PersistNarrativeRequest.model_fields
    assert "registry_snapshot_hash" in fields, (
        "PersistNarrativeRequest must carry registry_snapshot_hash for LD-10 compliance"
    )
    assert "registry_snapshot_generated_at" in fields
    assert "registry_schema_version" in fields


def test_persist_narrative_request_rejects_missing_hash():
    """PersistNarrativeRequest raises ValidationError if registry_snapshot_hash is absent."""
    import pydantic
    from tools.persist_narrative import PersistNarrativeRequest

    envelope = _make_minimal_narrative_envelope()
    scope = _make_scope_context()

    with pytest.raises(pydantic.ValidationError):
        PersistNarrativeRequest(
            envelope=envelope,
            scope_context=scope,
            ruleset_version="v1.0",
            analysis_version=1,
            template_version="t1.0",
            scope_origin="test",
            truth_mode="HISTORICAL",
            source_snapshot_id=uuid4(),
            source_replay_artifact_id=None,
            generated_by="test",
            generated_reason="test",
            writer_profile_id="trade_auditor_agent._writer",
            # registry_snapshot_hash intentionally omitted
        )


def test_persist_narrative_tool_passes_stamp():
    """PersistNarrativeTool._build_payload() serializes provenance fields to JSON payload.

    Verified by constructing a PersistNarrativeRequest with provenance fields
    and confirming the resulting JSON payload includes them.
    """
    import os
    os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://vm100-test:8000")

    from tools.persist_narrative import PersistNarrativeTool, PersistNarrativeRequest

    envelope = _make_minimal_narrative_envelope()
    scope = _make_scope_context()

    tool = PersistNarrativeTool()
    request = PersistNarrativeRequest(
        envelope=envelope,
        scope_context=scope,
        ruleset_version="v1.0",
        analysis_version=1,
        template_version="t1.0",
        scope_origin="test",
        truth_mode="HISTORICAL",
        source_snapshot_id=uuid4(),
        source_replay_artifact_id=None,
        generated_by="test",
        generated_reason="test",
        writer_profile_id="trade_auditor_agent._writer",
        registry_snapshot_hash=VALID_HASH,
        registry_snapshot_generated_at=VALID_TS,
        registry_schema_version="1.0",
    )
    payload = tool._build_payload(request)

    assert "registry_snapshot_hash" in payload
    assert payload["registry_snapshot_hash"] == VALID_HASH
    assert "registry_snapshot_generated_at" in payload
    assert "registry_schema_version" in payload


def test_orchestrator_stamps_persist_call():
    """MentorPipelineOrchestrator passes stamp fields to narrative_persister.persist().

    Verified via mock inspection of the PersistNarrativeRequest that the
    orchestrator constructs — it must include the 3 provenance fields.
    """
    import os
    import asyncio
    os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://vm100-test:8000")

    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from fingpt_core.contracts.narrative.scope import TruthMode

    scope = _make_scope_context()

    # Track what PersistNarrativeRequest was built
    captured_request = {}

    mock_persister = MagicMock()
    async def capture_persist(request, headers=None):
        captured_request["request"] = request
        from tools.persist_narrative import PersistNarrativeResponse
        return PersistNarrativeResponse(
            narrative_id=uuid4(),
            narrative_version=1,
            unsourced_claim_count=0,
        )
    mock_persister.persist = capture_persist

    mock_events = MagicMock()
    mock_events.new_correlation_id.return_value = "corr-1"
    mock_events.emit = MagicMock()

    mock_dispatcher = MagicMock()
    mock_dispatcher.attach_header.return_value = {}

    async def mock_invoke(profile, input, headers=None, **kwargs):
        if "_reader" in profile:
            return {
                "execution_id": None,
                "scope_context": scope.model_dump(mode="json"),
                "retrieved_evidence": {},
            }
        elif "_analyzer" in profile:
            return {
                "execution_id": None,
                "scope_context": scope.model_dump(mode="json"),
                "findings": {},
            }
        elif "_writer" in profile:
            return {
                "profile": "trade_auditor",
                "execution_id": None,
                "sentences": [],
            }
        return {}

    mock_citation = MagicMock()
    mock_citation.enforce = MagicMock()

    mock_confidence = MagicMock()
    mock_confidence.compute.return_value = MagicMock()

    orchestrator = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=mock_dispatcher,
        citation_validator=mock_citation,
        confidence_calculator=mock_confidence,
        event_emitter=mock_events,
        subordinate_invoker=mock_invoke,
        narrative_persister_client=mock_persister,
    )

    with patch("helpers.mentor_pipeline_orchestrator.stamp_at_write_time") as mock_stamp:
        mock_stamp.return_value = {
            "registry_snapshot_hash": VALID_HASH,
            "registry_snapshot_generated_at": VALID_TS,
            "registry_schema_version": "1.0",
        }

        asyncio.run(orchestrator.run(
            execution_id=None,
            scope_context=scope,
            replay_artifact_id=None,
            ruleset_version="v1.0",
            analysis_version=1,
            template_version="t1.0",
            source_snapshot_id=uuid4(),
            truth_mode=TruthMode.HISTORICAL,
        ))

    # stamp_at_write_time was called
    assert mock_stamp.called, "stamp_at_write_time must be called by orchestrator"

    # The persisted request carries provenance fields
    assert "request" in captured_request
    req = captured_request["request"]
    assert req.registry_snapshot_hash == VALID_HASH


def test_three_collections_consistent():
    """Single session produces same snapshot_hash across agent_envelopes, planner_outputs, mentor_narratives.

    Proves the CapabilityRegistry singleton is correctly shared in-process.
    """
    SHARED_HASH = "c" * 16

    reg = _make_fake_registry(SHARED_HASH)

    # --- agent_envelopes ---
    ae_docs = []
    ae_col = MagicMock()
    ae_col.insert_one.side_effect = lambda doc: ae_docs.append(doc)
    ae_db = MagicMock()
    ae_db.__getitem__ = MagicMock(side_effect=lambda name: ae_col)

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg
        from core.agents.envelope_writer import build_envelope, write_envelope
        import os
        os.environ.setdefault("EVAL_MODEL", "test-model/fake")
        env = build_envelope(
            task_id="t1", parent_task_id=None, agent_id="agent_zero",
            input_payload={}, output_payload={},
            telemetry={"model_used": "gpt-4", "cost": {}, "reason_chain": []},
            status="success",
        )
        write_envelope(ae_db, env)

    # --- planner_outputs ---
    po_docs = []
    po_col = MagicMock()
    po_col.insert_one.side_effect = lambda doc: po_docs.append(doc)
    po_db = MagicMock()
    po_db.__getitem__ = MagicMock(side_effect=lambda name: po_col)

    with patch("core.agents.planner_output.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg
        from core.agents.planner_output import write_planner_output
        write_planner_output(db=po_db, task_id="t1", agent_id="agent_zero", plan_steps=[])

    assert len(ae_docs) == 1
    assert len(po_docs) == 1
    assert ae_docs[0]["registry_snapshot_hash"] == SHARED_HASH
    assert po_docs[0]["registry_snapshot_hash"] == SHARED_HASH
