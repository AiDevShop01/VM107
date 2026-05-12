"""Tests for ConfidenceVectorCalculator — CTX-§9 deterministic computation.

ConfidenceVectorCalculator computes the 5-dimensional ConfidenceVector
deterministically from the structured sentence array + replay metadata +
regime snapshot age. Writer NEVER supplies this vector.

Plans: 60-04
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from fingpt_core.contracts.narrative.citation import CitationToken
from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(sentences: list[NarrativeSentence]) -> NarrativeEnvelope:
    return NarrativeEnvelope(
        profile="trade_auditor",
        execution_id=uuid4(),
        sentences=sentences,
    )


def _make_citation(registry_id: str, field: str = "value") -> CitationToken:
    return CitationToken(registry_id=registry_id, field=field)


def _make_replay_citation(field: str, frame: int | None = None) -> CitationToken:
    return CitationToken(registry_id="replay_line", field=field, frame_anchor=frame)


def _make_sentence(
    idx: int,
    cls: SentenceClass,
    text: str,
    citations: list[CitationToken] | None = None,
) -> NarrativeSentence:
    return NarrativeSentence(
        sentence_index=idx,
        sentence_class=cls,
        text=text,
        citations=citations or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_deterministic_computation():
    """CTX-§9 — ConfidenceVector computed deterministically from sentence array.

    Same envelope + same replay_metadata + same regime age → identical vector every call.
    """
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    cite = _make_citation("behavioral_analysis_tool")
    envelope = _make_envelope([
        _make_sentence(0, SentenceClass.ASSERTION, "The trader hesitated.", [cite]),
        _make_sentence(1, SentenceClass.TRANSITION, "Moving on."),
    ])
    replay_meta = {}
    age = 2.0

    v1 = calc.compute(envelope, replay_meta, age)
    v2 = calc.compute(envelope, replay_meta, age)

    assert v1 == v2


def test_citation_coverage_all_cited():
    """citation_coverage == 1.0 when all ASSERTION sentences have citations."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    cite = _make_citation("execution_quality_tool")
    sentences = [
        _make_sentence(i, SentenceClass.ASSERTION, f"Claim {i}.", [cite])
        for i in range(3)
    ]
    v = calc.compute(_make_envelope(sentences))
    assert v.citation_coverage == 1.0


def test_citation_coverage_partial():
    """citation_coverage == 0.5 when 2 of 4 ASSERTIONs are cited."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    cite = _make_citation("execution_quality_tool")
    sentences = [
        _make_sentence(0, SentenceClass.ASSERTION, "Cited claim 1.", [cite]),
        _make_sentence(1, SentenceClass.ASSERTION, "Cited claim 2.", [cite]),
        _make_sentence(2, SentenceClass.ASSERTION, "Uncited claim 3."),
        _make_sentence(3, SentenceClass.ASSERTION, "Uncited claim 4."),
    ]
    v = calc.compute(_make_envelope(sentences))
    assert v.citation_coverage == 0.5


def test_citation_coverage_no_assertions():
    """citation_coverage == 0.0 when there are no ASSERTION sentences."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    sentences = [
        _make_sentence(0, SentenceClass.TRANSITION, "Transition."),
        _make_sentence(1, SentenceClass.SUMMARY, "Summary."),
    ]
    v = calc.compute(_make_envelope(sentences))
    # 0 cited / max(1, 0) = 0.0
    assert v.citation_coverage == 0.0


def test_source_diversity():
    """source_diversity == count of distinct registry_ids cited across the envelope."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    sentences = [
        _make_sentence(0, SentenceClass.ASSERTION, "Behavioral claim.", [
            _make_citation("behavioral_analysis_tool"),
        ]),
        _make_sentence(1, SentenceClass.ASSERTION, "Replay claim.", [
            _make_citation("replay_line", "abc-123"),
        ]),
        _make_sentence(2, SentenceClass.ASSERTION, "Quality claim.", [
            _make_citation("execution_quality_tool"),
        ]),
    ]
    v = calc.compute(_make_envelope(sentences))
    assert v.source_diversity == 3


def test_behavioral_density_full():
    """behavioral_evidence_density == 1.0 for behavioral claim cited via behavioral_analysis_tool."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    sentences = [
        _make_sentence(
            0, SentenceClass.ASSERTION,
            "The trader showed hesitation before entry.",
            [_make_citation("behavioral_analysis_tool", "hesitation_seconds")],
        ),
    ]
    v = calc.compute(_make_envelope(sentences))
    assert v.behavioral_evidence_density == 1.0


def test_behavioral_density_partial():
    """behavioral_evidence_density == 0.5 for behavioral claim cited via generic replay_line."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    sentences = [
        _make_sentence(
            0, SentenceClass.ASSERTION,
            "The trader showed hesitation before entry.",
            [_make_citation("replay_line", "frame_data")],
        ),
    ]
    v = calc.compute(_make_envelope(sentences))
    assert v.behavioral_evidence_density == 0.5


def test_behavioral_density_no_claims():
    """behavioral_evidence_density defaults to 1.0 when no behavioral-claim ASSERTIONs exist."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    cite = _make_citation("execution_quality_tool")
    sentences = [
        _make_sentence(0, SentenceClass.ASSERTION, "The entry was timely.", [cite]),
        _make_sentence(1, SentenceClass.ASSERTION, "The exit captured 80% of the move.", [cite]),
    ]
    v = calc.compute(_make_envelope(sentences))
    # No behavioral-pattern keywords → default to 1.0
    assert v.behavioral_evidence_density == 1.0


def test_replay_completeness_all_resolved():
    """replay_completeness == 1.0 when all replay_line citations are resolved."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    # Two replay citations
    c0 = _make_replay_citation("abc-123", 42)
    c1 = _make_replay_citation("def-456", 10)
    sentences = [
        _make_sentence(0, SentenceClass.ASSERTION, "Frame analysis.", [c0]),
        _make_sentence(1, SentenceClass.ASSERTION, "Entry frame.", [c1]),
    ]
    replay_meta = {
        "replay_line:abc-123@frame_42": True,
        "replay_line:def-456@frame_10": True,
    }
    v = calc.compute(_make_envelope(sentences), replay_meta)
    assert v.replay_completeness == 1.0


def test_replay_completeness_partial():
    """replay_completeness == 0.5 when only 1 of 2 replay citations resolved."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    c0 = _make_replay_citation("abc-123", 42)
    c1 = _make_replay_citation("def-456", 10)
    sentences = [
        _make_sentence(0, SentenceClass.ASSERTION, "Frame analysis.", [c0]),
        _make_sentence(1, SentenceClass.ASSERTION, "Entry frame.", [c1]),
    ]
    replay_meta = {
        "replay_line:abc-123@frame_42": True,
        "replay_line:def-456@frame_10": False,
    }
    v = calc.compute(_make_envelope(sentences), replay_meta)
    assert v.replay_completeness == 0.5


def test_regime_data_freshness_passthrough():
    """regime_data_freshness_hours is passed through unchanged."""
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator

    calc = ConfidenceVectorCalculator()
    v = calc.compute(_make_envelope([]), regime_snapshot_age_hours=4.5)
    assert v.regime_data_freshness_hours == 4.5
