"""Phase 60 Plan 60-12 — E2E golden-trade smoke test.

Uses a known deterministic trade fixture (golden trade) to run the full
mentor pipeline (reader -> analyzer -> writer) end-to-end with mocked
LLM calls and mocked VM100 persist.  Asserts citation_coverage >= 0.8.

CTX-§10 LOCKED — idempotency key is not tested here (that lives in the
Dagster sensor tests). This test validates the MentorPipelineOrchestrator
stage flow and ConfidenceVector computation.

Mocking strategy:
  - subordinate_invoker: returns deterministic reader/analyzer/writer dicts
    with valid citations so citation_coverage >= 0.8 is guaranteed.
  - narrative_persister_client: no-op async mock (VM100 phase-39 locked).
  - event_emitter: simple recording mock (does not affect outcome).
  - ScopeDispatcher: real instance with SCOPE_DISPATCHER_SECRET_KEY env var.
  - CitationValidator: real instance pointed at VM107/registry.
  - ConfidenceVectorCalculator: real instance.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_REGISTRY_ROOT = _VM107_ROOT / "registry"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_golden_trade() -> dict:
    return json.loads((_FIXTURES_DIR / "golden_trade.json").read_text())


def _build_valid_reader_output(execution_id: str) -> dict:
    """Build a minimal valid ReaderOutput dict with scope_context injected.

    retrieved_evidence is dict[str, Any] — keyed by source type.
    suspicious_payload is list[str] — empty list (no injection detected).
    """
    now = datetime.now(timezone.utc).isoformat()
    expires = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "execution_id": execution_id,
        "scope_context": {
            "schema_version": "1.0",
            "profile_id": "trade_auditor_agent",
            "account_id": "golden-acc-001",
            "execution_id": execution_id,
            "truth_mode": "HISTORICAL",
            "narrative_visibility": "NONE",
            "issued_at": now,
            "expires_at": expires,
        },
        # retrieved_evidence: dict[str, Any] — keyed by source type (not a list)
        "retrieved_evidence": {
            "behavioral_patterns": {
                "revenge_trade": True,
                "hesitation": False,
                "fomo_entry": False,
            },
            "trade_summary": {
                "instrument": "EUR/USD",
                "pnl": -30.0,
                "mae": -35.0,
                "mfe": 15.0,
            },
        },
        "suspicious_payload": [],
    }


def _build_valid_analyzer_output(execution_id: str) -> dict:
    """Build a minimal valid AnalyzerOutput dict.

    findings is dict[str, Any] — structured per-profile shape.
    """
    now = datetime.now(timezone.utc).isoformat()
    expires = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "execution_id": execution_id,
        "scope_context": {
            "schema_version": "1.0",
            "profile_id": "trade_auditor_agent",
            "account_id": "golden-acc-001",
            "execution_id": execution_id,
            "truth_mode": "HISTORICAL",
            "narrative_visibility": "NONE",
            "issued_at": now,
            "expires_at": expires,
        },
        # findings: dict[str, Any] — keyed by finding category (not a list)
        "findings": {
            "behavioral_markers": [
                {
                    "finding_type": "behavioral_marker",
                    "registry_id": "behavioral_pattern",
                    "field": "revenge_trade",
                    "severity": "HIGH",
                    "description": "Trade entered immediately after a prior loss.",
                }
            ],
            "risk_summary": {
                "pnl": -30.0,
                "mae": -35.0,
                "trade_quality": "POOR",
            },
        },
        "cited_registry_ids": ["behavioral_pattern"],
    }


def _build_valid_writer_output(execution_id: str) -> dict:
    """Build a NarrativeEnvelope dict with citation_coverage >= 0.8.

    6 ASSERTION sentences, all 6 with citations -> citation_coverage = 1.0.
    Citations reference registry IDs as loaded by CitationValidator from YAML `id` fields:
      - revenge_trade  (registry/behavioral_pattern/revenge_trade.yaml id=revenge_trade)
      - hesitation     (registry/behavioral_pattern/hesitation.yaml id=hesitation)
    confidence_vector=None (MANDATORY: orchestrator owns this per CTX-§9).
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "profile": "trade_auditor_agent",
        "execution_id": execution_id,
        "sentences": [
            {
                "schema_version": "1.0",
                "sentence_index": 0,
                "sentence_class": "META",
                "text": "Trade audit for EUR/USD LONG opened 2026-05-01.",
                "citations": [],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 1,
                "sentence_class": "ASSERTION",
                "text": (
                    "The entry followed a losing trade within the session "
                    "[ref:revenge_trade:revenge_trade]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "revenge_trade",
                        "field": "revenge_trade",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 2,
                "sentence_class": "ASSERTION",
                "text": (
                    "The revenge_trade behavioral marker was flagged true "
                    "[ref:revenge_trade:revenge_trade]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "revenge_trade",
                        "field": "revenge_trade",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 3,
                "sentence_class": "ASSERTION",
                "text": (
                    "The trade closed with a loss of 30 pips "
                    "[ref:revenge_trade:revenge_trade]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "revenge_trade",
                        "field": "revenge_trade",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 4,
                "sentence_class": "ASSERTION",
                "text": (
                    "MAE reached -35 pips before any MFE upside "
                    "[ref:revenge_trade:revenge_trade]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "revenge_trade",
                        "field": "revenge_trade",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 5,
                "sentence_class": "ASSERTION",
                "text": (
                    "The 47-minute duration suggests impulsive trade management "
                    "[ref:revenge_trade:revenge_trade]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "revenge_trade",
                        "field": "revenge_trade",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 6,
                "sentence_class": "ASSERTION",
                "text": (
                    "No hesitation pattern was detected in this execution "
                    "[ref:hesitation:hesitation]."
                ),
                "citations": [
                    {
                        "schema_version": "1.0",
                        "registry_id": "hesitation",
                        "field": "hesitation",
                        "frame_anchor": None,
                        "resolved_at": now,
                    }
                ],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 7,
                "sentence_class": "TRANSITION",
                "text": "Reviewing these patterns before the next session is recommended.",
                "citations": [],
                "unsourced": False,
            },
            {
                "schema_version": "1.0",
                "sentence_index": 8,
                "sentence_class": "SUMMARY",
                "text": "Overall, this trade is a textbook revenge-trade failure.",
                "citations": [],
                "unsourced": False,
            },
        ],
        "loaded_skills": ["citation-discipline"],
        "confidence_vector": None,
        "unsourced_claim_count": 0,
    }


# ---------------------------------------------------------------------------
# Event emitter mock
# ---------------------------------------------------------------------------


class _RecordingEventEmitter:
    """Records emitted events for test assertions."""

    def __init__(self):
        self.events: list[dict] = []
        self._counter = 0

    def new_correlation_id(self) -> str:
        self._counter += 1
        return f"corr-{self._counter:04d}"

    def emit(self, event_type: str, category: str, correlation_id: str, payload: dict):
        self.events.append(
            {
                "event_type": event_type,
                "category": category,
                "correlation_id": correlation_id,
                "payload": payload,
            }
        )


# ---------------------------------------------------------------------------
# Main E2E test
# ---------------------------------------------------------------------------


def test_golden_trade_citation_coverage_at_least_080():
    """E2E — golden-trade fixture produces narrative with citation_coverage >= 0.8.

    The full MentorPipelineOrchestrator stage flow (reader -> analyzer -> writer)
    runs with mocked LLM subordinate_invoker and mocked VM100 persist.
    Asserts the final NarrativeEnvelope.confidence_vector.citation_coverage >= 0.8.
    """
    golden = _load_golden_trade()
    execution_id = golden["execution_id"]
    account_id = golden["account_id"]
    source_snapshot_id = golden["source_snapshot_id"]
    expected_min_coverage = golden["expected"]["citation_coverage_min"]

    # ── Build dependencies ──────────────────────────────────────────────────
    from fingpt_core.contracts.narrative.scope import (
        NarrativeVisibility,
        ScopeContext,
        TruthMode,
    )
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.scope_dispatcher import ScopeDispatcher

    # Real helpers wired against actual VM107/registry
    scope_dispatcher = ScopeDispatcher(
        secret_key=os.environ.get("SCOPE_DISPATCHER_SECRET_KEY", "test-golden-key")
    )
    citation_validator = CitationValidator(registry_root=_REGISTRY_ROOT)
    confidence_calculator = ConfidenceVectorCalculator()
    event_emitter = _RecordingEventEmitter()

    # Mocked subordinate_invoker — returns deterministic stage outputs
    reader_output_dict = _build_valid_reader_output(execution_id)
    analyzer_output_dict = _build_valid_analyzer_output(execution_id)
    writer_output_dict = _build_valid_writer_output(execution_id)

    invoke_call_order = {"n": 0}

    async def _mock_invoker(profile: str, input: Any) -> dict:
        invoke_call_order["n"] += 1
        if "_reader" in profile:
            return reader_output_dict
        elif "_analyzer" in profile:
            return analyzer_output_dict
        elif "_writer" in profile:
            return writer_output_dict
        raise ValueError(f"Unknown sub-profile in mock invoker: {profile}")

    # Mocked VM100 persist client (Phase 39 typed-API lock — never direct DB)
    narrative_persister_client = MagicMock()
    narrative_persister_client.persist = AsyncMock(return_value=None)

    # ── Instantiate orchestrator ────────────────────────────────────────────
    orchestrator = MentorPipelineOrchestrator(
        profile="trade_auditor_agent",
        scope_dispatcher=scope_dispatcher,
        citation_validator=citation_validator,
        confidence_calculator=confidence_calculator,
        event_emitter=event_emitter,
        subordinate_invoker=_mock_invoker,
        narrative_persister_client=narrative_persister_client,
        max_writer_retries=2,
    )

    # ── Build scope context ─────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    scope_context = ScopeContext(
        profile_id="trade_auditor_agent",
        account_id=account_id,
        execution_id=UUID(execution_id),
        truth_mode=TruthMode.HISTORICAL,
        narrative_visibility=NarrativeVisibility.NONE,
        issued_at=now,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )

    # ── Run orchestrator (sync wrapper per BLOCKER #5 pattern) ─────────────
    envelope = asyncio.run(
        orchestrator.run(
            execution_id=UUID(execution_id),
            scope_context=scope_context,
            replay_artifact_id=None,
            ruleset_version=golden["ruleset_version"],
            analysis_version=golden["analysis_version"],
            template_version=golden["template_version"],
            source_snapshot_id=UUID(source_snapshot_id),
            truth_mode=TruthMode.HISTORICAL,
            replay_metadata={},
            regime_snapshot_age_hours=golden["regime_snapshot_age_hours"],
        )
    )

    # ── Assertions ──────────────────────────────────────────────────────────

    # 1. Pipeline must complete (all 3 stages invoked)
    assert invoke_call_order["n"] == 3, (
        f"Expected 3 subordinate_invoker calls (reader+analyzer+writer) "
        f"but got {invoke_call_order['n']}"
    )

    # 2. Narrative must be persisted exactly once
    narrative_persister_client.persist.assert_called_once()

    # 3. confidence_vector must be injected by orchestrator
    assert envelope.confidence_vector is not None, (
        "Orchestrator must inject confidence_vector after writer seals envelope"
    )

    # 4. citation_coverage must meet threshold
    actual_coverage = envelope.confidence_vector.citation_coverage
    assert actual_coverage >= expected_min_coverage, (
        f"citation_coverage {actual_coverage:.3f} < required {expected_min_coverage}. "
        f"Golden trade fixture requires >= {expected_min_coverage} cited ASSERTION sentences."
    )

    # 5. Event lifecycle must be emitted (mentor_pipeline_started/completed)
    event_types = [e["event_type"] for e in event_emitter.events]
    assert "mentor_pipeline_started" in event_types, "mentor_pipeline_started not emitted"
    assert "mentor_pipeline_completed" in event_types, "mentor_pipeline_completed not emitted"
    assert "reader_completed" in event_types, "reader_completed not emitted"
    assert "analyzer_completed" in event_types, "analyzer_completed not emitted"
    assert "writer_completed" in event_types, "writer_completed not emitted"

    # 6. Profile in envelope must match
    assert envelope.profile == "trade_auditor_agent", (
        f"envelope.profile mismatch: got {envelope.profile!r}"
    )
