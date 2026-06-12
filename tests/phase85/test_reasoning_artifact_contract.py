"""Phase 85 Plan 02 — Task 1 (RED): ReasoningArtifactContract Pydantic v2 contract tests.

Tests the 15-field B1 schema from Brain Part 2 §B1 lines 184-203:
- All 15 fields present and round-trip correctly
- frozen=True means mutation raises ValidationError
- Default empty list for citations
- confidence_self_report nullable (None is valid; to be filled by B5)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.phase_85


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_artifact():
    """Canonical sample that populates all 15 fields verbatim."""
    return {
        "artifact_id": uuid.uuid4(),
        "agent_profile_id": "vm107.macro_release_analyst",
        "sub_profile_id": None,
        "iteration": 1,
        "parent_envelope_id": uuid.uuid4(),
        "reasoning_text": "CPI came in at 3.4 vs 3.3 consensus — hawkish surprise.",
        "reasoning_tokens": 42,
        "response_text": "The dollar should strengthen on the beat.",
        "response_tokens": 18,
        "tool_called": "lookup_macro_indicator",
        "tool_args": {"indicator_id": "CPIAUCSL"},
        "timestamp": datetime(2026, 6, 12, 12, 30, 0, tzinfo=timezone.utc),
        "model_version": "claude-3-7-sonnet-20250219",
        "prompt_version": "macro_release_v1",
        "confidence_self_report": None,
        "citations": [],
    }


# ── tests ─────────────────────────────────────────────────────────────────────

def test_all_fifteen_fields_present(sample_artifact):
    """All 15 fields instantiate and round-trip without loss."""
    from contracts.reasoning_artifact import ReasoningArtifactContract

    artifact = ReasoningArtifactContract(**sample_artifact)

    assert artifact.artifact_id == sample_artifact["artifact_id"]
    assert artifact.agent_profile_id == "vm107.macro_release_analyst"
    assert artifact.sub_profile_id is None
    assert artifact.iteration == 1
    assert artifact.parent_envelope_id == sample_artifact["parent_envelope_id"]
    assert artifact.reasoning_text == "CPI came in at 3.4 vs 3.3 consensus — hawkish surprise."
    assert artifact.reasoning_tokens == 42
    assert artifact.response_text == "The dollar should strengthen on the beat."
    assert artifact.response_tokens == 18
    assert artifact.tool_called == "lookup_macro_indicator"
    assert artifact.tool_args == {"indicator_id": "CPIAUCSL"}
    assert artifact.timestamp == sample_artifact["timestamp"]
    assert artifact.model_version == "claude-3-7-sonnet-20250219"
    assert artifact.prompt_version == "macro_release_v1"
    assert artifact.confidence_self_report is None
    assert artifact.citations == []


def test_frozen_raises_on_mutation(sample_artifact):
    """frozen=True — attribute assignment must raise ValidationError."""
    from contracts.reasoning_artifact import ReasoningArtifactContract

    artifact = ReasoningArtifactContract(**sample_artifact)

    with pytest.raises((ValidationError, TypeError)):
        # Pydantic v2 frozen models raise ValidationError on attribute set;
        # some test runners surface as TypeError — accept either.
        artifact.reasoning_text = "mutated"


def test_default_citations_empty_list():
    """Citations field defaults to [] when not provided."""
    from contracts.reasoning_artifact import ReasoningArtifactContract

    artifact = ReasoningArtifactContract(
        artifact_id=uuid.uuid4(),
        agent_profile_id="vm107.macro_release_analyst",
        iteration=0,
        reasoning_text="test",
        reasoning_tokens=5,
        response_text="ok",
        response_tokens=2,
        timestamp=datetime.now(timezone.utc),
        model_version="test-model",
        prompt_version="v0",
    )
    assert artifact.citations == []


def test_confidence_self_report_nullable(sample_artifact):
    """confidence_self_report=None is valid (filled by future B5)."""
    from contracts.reasoning_artifact import ReasoningArtifactContract

    sample_artifact["confidence_self_report"] = None
    artifact = ReasoningArtifactContract(**sample_artifact)
    assert artifact.confidence_self_report is None


def test_confidence_self_report_float_valid(sample_artifact):
    """confidence_self_report accepts float values."""
    from contracts.reasoning_artifact import ReasoningArtifactContract

    sample_artifact["confidence_self_report"] = 0.75
    artifact = ReasoningArtifactContract(**sample_artifact)
    assert artifact.confidence_self_report == 0.75


def test_citation_ref_fields():
    """CitationRef has citation_id, source, and optional snippet."""
    from contracts.reasoning_artifact import CitationRef

    ref = CitationRef(citation_id="cit-001", source="FRED", snippet="CPI at 3.4%")
    assert ref.citation_id == "cit-001"
    assert ref.source == "FRED"
    assert ref.snippet == "CPI at 3.4%"

    ref_no_snippet = CitationRef(citation_id="cit-002", source="BLS")
    assert ref_no_snippet.snippet is None


def test_artifact_with_citations(sample_artifact):
    """Citations list with CitationRef objects round-trips correctly."""
    from contracts.reasoning_artifact import CitationRef, ReasoningArtifactContract

    sample_artifact["citations"] = [
        CitationRef(citation_id="cit-001", source="FRED", snippet="CPI at 3.4"),
    ]
    artifact = ReasoningArtifactContract(**sample_artifact)
    assert len(artifact.citations) == 1
    assert artifact.citations[0].citation_id == "cit-001"
