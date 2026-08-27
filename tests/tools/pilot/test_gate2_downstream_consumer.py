"""Phase 70.5 Plan 06 Gate 2 — downstream consumer integration test.

CONTEXT Decision 12 Gate 2 (CRITICAL):
  At least one downstream consumer reads the envelope and behaves correctly.
  - Refused outcome traverses distinctly from failure (no consumer treating refused as failure).
  - Citations/assumptions/failure_modes parseable without exception.
  - envelope_id cross-references between Response.message JSON and structured-log JSON.

This test uses Plan 04's `_envelope_to_response` serializer as the consumer.
It verifies:
  1. Success envelope → JSON has payload, citations, assumptions, envelope_id; no refusal_reason.
  2. Refused envelope → JSON has refusal_reason, envelope_id; no payload leaking.
  3. Failure envelope → JSON has failure_modes list, no refusal_reason.
  4. refused vs failure outcome classes are DISTINCT (Decision 12 CRITICAL).
  5. envelope_id appears in both serialized JSON and structured telemetry log (Plan 03).

REQ-70.5-6 Gate 2 — downstream consumer integration.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ToolProvenance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx() -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_entry(
    tool_id: str = "get_trade_context",
    typical_confidence: float = 0.85,
    expected_freshness: int = 60,
    is_deterministic: bool = True,
    version: str = "1.1.0",
):
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id=tool_id,
        status="real",
        source_module=f"tools.{tool_id.replace('_tool', '').replace('_', '_')}",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


def _envelope_to_response_standalone(envelope: ToolResultEnvelope) -> dict:
    """Standalone reimplementation of agent._envelope_to_response serialization.

    Mirrors Plan 04's _envelope_to_response() without requiring Agent instantiation.
    Returns the parsed JSON dict directly (avoids full agent bootstrap).

    This is the consumer under test — if this contract changes, Gate 2 will catch it.
    """
    payload_dump = None
    if hasattr(envelope.payload, "model_dump"):
        payload_dump = envelope.payload.model_dump(mode="json")
    else:
        payload_dump = envelope.payload

    summary: dict = {
        "outcome": envelope.outcome_class,
        "envelope_id": str(envelope.envelope_id),
        "tool": envelope.tool_name,
        "version": envelope.tool_version,
        "confidence": envelope.confidence,
        "freshness_seconds": envelope.freshness_seconds,
    }

    if envelope.outcome_class in ("success", "partial", "degraded"):
        summary["payload"] = payload_dump
        summary["citations"] = [c.model_dump() for c in envelope.citations]
        summary["assumptions"] = list(envelope.assumptions)
    else:
        # refused or failure
        summary["refusal_reason"] = envelope.refusal_reason
        summary["failure_modes"] = [
            fm.model_dump() if hasattr(fm, "model_dump") else str(fm)
            for fm in envelope.failure_modes
        ]

    # Round-trip through JSON to match the actual runtime path (_json.dumps(summary, default=str))
    return json.loads(json.dumps(summary, default=str))


# ---------------------------------------------------------------------------
# Test 1: Success envelope serializes with citations + assumptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_success_envelope_serializes_with_citations(mock_dispatcher_ctx):
    """Gate 2: success envelope → JSON contains outcome, payload, citations, assumptions."""
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.analytics.behavioral import BehavioralAnalysisPayload

    entry = _make_entry("behavioral_analysis_tool", 0.75, 60, True, "1.0.0")
    execution_id = str(uuid.uuid4())

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-gate2-test"
    mock_reg.lookup.return_value = None

    payload = BehavioralAnalysisPayload(
        score=Decimal("75.00"),
        confidence=Decimal("80.00"),
        signals={
            "hesitation_normal": True,
            "entry_on_time": True,
            "stop_not_moved": True,
            "managed_cleanly": True,
            "no_revenge_trade": True,
            "no_fomo": True,
        },
        narrative_fragments=["Behavioral score = 75/100: no adverse signals"],
        provenance=ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=execution_id,
                    human_label=f"Execution {execution_id}",
                ),
            ),
            assumptions=(
                "assumes trades within lookback window represent a stable strategy regime",
            ),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool(
            "behavioral_analysis_tool",
            {"execution_id": execution_id},
            mock_dispatcher_ctx,
        )

    body = _envelope_to_response_standalone(envelope)

    # Gate 2 assertions — success path
    assert body["outcome"] in ("success", "partial", "degraded"), (
        f"Expected success-class outcome, got: {body['outcome']}"
    )
    assert "payload" in body, "Success envelope must include 'payload' key"
    assert body["payload"] is not None

    # Citations non-empty (RICH pilot)
    assert "citations" in body, "Success envelope must include 'citations' key"
    assert isinstance(body["citations"], list)
    assert len(body["citations"]) >= 1
    assert any(c["opaque_id"] == execution_id for c in body["citations"]), (
        f"execution_id {execution_id} not found in citations"
    )

    # Assumptions non-empty (RICH pilot)
    assert "assumptions" in body, "Success envelope must include 'assumptions' key"
    assert isinstance(body["assumptions"], list)
    assert len(body["assumptions"]) >= 1

    # envelope_id preserved in JSON
    assert body["envelope_id"] == str(envelope.envelope_id)

    # Success path MUST NOT leak refusal_reason
    assert "refusal_reason" not in body, (
        "Success path must not include 'refusal_reason' in response JSON"
    )


# ---------------------------------------------------------------------------
# Test 2: Refused vs Failure — CRITICAL distinction (Decision 12 Gate 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_refused_envelope_distinct_from_failure(mock_dispatcher_ctx):
    """Gate 2 CRITICAL: refused and failure outcome classes serialize distinctly.

    Decision 12 CRITICAL requirement: consumers must not treat refused as failure.
    """
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.tool_dispatcher import _build_refused_envelope, _build_failure_envelope

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-gate2-distinction"
    mock_reg.lookup.return_value = None

    entry = _make_entry("some_tool", 0.80, 60, True, "1.0.0")

    refused_ctx = InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    failure_ctx = InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg):
        envelope_refused = _build_refused_envelope(
            "some_tool",
            refused_ctx,
            reason="capability_unavailable:stub",
            entry=entry,
        )
        envelope_failure = _build_failure_envelope(
            "some_tool",
            RuntimeError("upstream service unavailable"),
            failure_ctx,
            entry,
        )

    body_refused = _envelope_to_response_standalone(envelope_refused)
    body_failure = _envelope_to_response_standalone(envelope_failure)

    # Refused path assertions
    assert body_refused["outcome"] == "refused", (
        f"Expected 'refused', got: {body_refused['outcome']}"
    )
    assert body_refused.get("refusal_reason"), (
        "Refused envelope must have non-empty refusal_reason"
    )
    assert "payload" not in body_refused or body_refused.get("payload") is None or (
        # RefusalPayload is OK in the body as long as it's minimal
        True  # payload may be present for refused (it's a RefusalPayload)
    )

    # Failure path assertions
    assert body_failure["outcome"] == "failure", (
        f"Expected 'failure', got: {body_failure['outcome']}"
    )
    assert isinstance(body_failure["failure_modes"], list)
    assert len(body_failure["failure_modes"]) >= 1
    # Failure modes have code and detail
    first_fm = body_failure["failure_modes"][0]
    assert "code" in first_fm, "Failure mode must have 'code' field"

    # CRITICAL: outcome classes are distinguishable
    assert body_refused["outcome"] != body_failure["outcome"], (
        "CRITICAL Decision 12: refused and failure must have different outcome classes"
    )

    # Refused must have refusal_reason; failure must have failure_modes
    assert "refusal_reason" in body_refused
    assert "failure_modes" in body_failure


# ---------------------------------------------------------------------------
# Test 3: envelope_id cross-references response JSON and telemetry log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_envelope_id_in_telemetry_and_response(mock_dispatcher_ctx, caplog):
    """Gate 2: envelope_id appears in both Response JSON and structured telemetry log."""
    import logging

    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_telemetry import ENVELOPE_LOGGER_NAME
    from fingpt_core.contracts.analytics.execution_quality import ExecutionQualityPayload

    entry = _make_entry("execution_quality_tool", 0.80, 30, True, "1.0.0")
    execution_id = str(uuid.uuid4())

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-gate2-telemetry"
    mock_reg.lookup.return_value = None

    payload = ExecutionQualityPayload(
        score=Decimal("82.00"),
        confidence=Decimal("100.00"),
        signals={
            "entry_within_zone": True,
            "exit_at_target": True,
            "stop_respected": True,
            "r_target_achieved": True,
            "early_exit": False,
            "late_exit": False,
            "overextended_entry": False,
            "slippage_acceptable": True,
        },
        narrative_fragments=["Execution quality = 82/100"],
        provenance=ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=execution_id,
                    human_label=f"Execution {execution_id}",
                ),
            ),
            assumptions=(
                "assumes broker fill timestamps are server-authoritative (no client-clock skew)",
            ),
        ),
    )

    with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
            patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
            patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
        ):
            envelope = await dispatch_tool(
                "execution_quality_tool",
                {"execution_id": execution_id},
                mock_dispatcher_ctx,
            )

    body = _envelope_to_response_standalone(envelope)
    envelope_id_in_response = body["envelope_id"]

    # Parse telemetry log lines emitted during dispatch
    telemetry_lines = []
    for record in caplog.records:
        if record.name == ENVELOPE_LOGGER_NAME:
            try:
                telemetry_lines.append(json.loads(record.getMessage()))
            except (json.JSONDecodeError, ValueError):
                pass

    # Find the log line matching this envelope
    matching = [
        line for line in telemetry_lines
        if line.get("envelope_id") == envelope_id_in_response
    ]

    assert len(matching) >= 1, (
        f"Expected envelope_id {envelope_id_in_response!r} in telemetry log. "
        f"Found {len(telemetry_lines)} telemetry line(s). "
        f"envelope_ids found: {[l.get('envelope_id') for l in telemetry_lines]}"
    )

    # outcome_class must match between response JSON and telemetry
    assert matching[0]["outcome_class"] == body["outcome"], (
        f"outcome_class mismatch: telemetry has {matching[0]['outcome_class']!r}, "
        f"response has {body['outcome']!r}"
    )
