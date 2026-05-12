"""Tests for CitationValidator — CTX-§4 citation enforcement.

CitationValidator is a deterministic Python guardrail that hard-fails
ASSERTION sentences without citations, unknown registry IDs, META with
citations, and assertion-shaped SUMMARY sentences without citations.

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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    """Create a minimal registry tree with known IDs for tests."""
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "behavioral_analysis_tool.yaml").write_text(
        "id: behavioral_analysis_tool\ntype: tool\n"
    )
    (tool_dir / "execution_quality_tool.yaml").write_text(
        "id: execution_quality_tool\ntype: tool\n"
    )

    bp_dir = tmp_path / "behavioral_pattern"
    bp_dir.mkdir()
    (bp_dir / "revenge_trade.yaml").write_text(
        "id: revenge_trade\ntype: behavioral_pattern\n"
    )
    (bp_dir / "hesitation.yaml").write_text(
        "id: hesitation\ntype: behavioral_pattern\n"
    )

    # Add the other 8 expected subdirs so load_known_registry_ids doesn't choke
    for subdir in [
        "replay_template", "event_type", "signal",
        "skill", "agent_profile", "service", "collection", "state_machine",
    ]:
        (tmp_path / subdir).mkdir()

    return tmp_path


def _make_envelope(sentences: list[NarrativeSentence]) -> NarrativeEnvelope:
    return NarrativeEnvelope(
        profile="trade_auditor",
        execution_id=uuid4(),
        sentences=sentences,
    )


def _make_citation(registry_id: str, field: str = "value") -> CitationToken:
    return CitationToken(registry_id=registry_id, field=field)


def _make_sentence(
    idx: int,
    cls: SentenceClass,
    text: str,
    citations: list[CitationToken] | None = None,
    unsourced: bool = False,
) -> NarrativeSentence:
    return NarrativeSentence(
        sentence_index=idx,
        sentence_class=cls,
        text=text,
        citations=citations or [],
        unsourced=unsourced,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_assertion_without_citation_rejected(registry_root: Path):
    """CTX-§4 — CitationValidator hard-fails ASSERTION without [ref:...]."""
    from helpers.citation_validator import CitationValidator, CitationViolation

    validator = CitationValidator(registry_root)
    envelope = _make_envelope([
        _make_sentence(0, SentenceClass.ASSERTION, "The trader hesitated before entry."),
    ])

    with pytest.raises(CitationViolation) as exc_info:
        validator.enforce(envelope)

    assert "ASSERTION" in str(exc_info.value)
    assert "citation" in str(exc_info.value).lower()


def test_unknown_registry_id_rejected(registry_root: Path):
    """CTX-§4 — CitationValidator hard-fails citation with unknown registry_id."""
    from helpers.citation_validator import CitationValidator, CitationViolation

    validator = CitationValidator(registry_root)
    citation = _make_citation("not_a_real_thing")
    envelope = _make_envelope([
        _make_sentence(0, SentenceClass.ASSERTION, "Claim with bad ref.", [citation]),
    ])

    with pytest.raises(CitationViolation) as exc_info:
        validator.enforce(envelope)

    assert "unknown registry_id" in str(exc_info.value)
    assert "not_a_real_thing" in str(exc_info.value)


def test_meta_with_citation_rejected(registry_root: Path):
    """CTX-§4 — META sentence with [ref:...] is rejected (META must not cite)."""
    from helpers.citation_validator import CitationValidator, CitationViolation

    validator = CitationValidator(registry_root)
    citation = _make_citation("behavioral_analysis_tool")
    envelope = _make_envelope([
        _make_sentence(0, SentenceClass.META, "Meta info about the trade.", [citation]),
    ])

    with pytest.raises(CitationViolation) as exc_info:
        validator.enforce(envelope)

    assert "META" in str(exc_info.value)


def test_summary_uncited_assertion_rejected(registry_root: Path):
    """CTX-§4 — SUMMARY with uncited factual claim (verb-of-claim + percentage) rejected."""
    from helpers.citation_validator import CitationValidator, CitationViolation

    validator = CitationValidator(registry_root)
    # Text contains "showed" (verb-of-claim) + a percentage
    envelope = _make_envelope([
        _make_sentence(
            0, SentenceClass.SUMMARY,
            "The trader showed a 4.2% improvement in execution quality.",
            citations=[],
        ),
    ])

    with pytest.raises(CitationViolation) as exc_info:
        validator.enforce(envelope)

    assert "SUMMARY" in str(exc_info.value)


def test_summary_uncited_framing_passes(registry_root: Path):
    """CTX-§4 — SUMMARY with neutral framing text and no citations passes."""
    from helpers.citation_validator import CitationValidator

    validator = CitationValidator(registry_root)
    envelope = _make_envelope([
        _make_sentence(
            0, SentenceClass.SUMMARY,
            "This concludes the review of the entry.",
            citations=[],
        ),
    ])

    # Should NOT raise
    validator.enforce(envelope)


def test_transition_no_citation_passes(registry_root: Path):
    """CTX-§4 — TRANSITION sentence without citation passes (citations optional)."""
    from helpers.citation_validator import CitationValidator

    validator = CitationValidator(registry_root)
    envelope = _make_envelope([
        _make_sentence(0, SentenceClass.TRANSITION, "Moving on to the exit analysis."),
    ])

    # Should NOT raise
    validator.enforce(envelope)


def test_known_registry_id_passes(registry_root: Path):
    """CTX-§4 — ASSERTION citing a valid registry_id passes."""
    from helpers.citation_validator import CitationValidator

    validator = CitationValidator(registry_root)
    citation = _make_citation("behavioral_analysis_tool")
    envelope = _make_envelope([
        _make_sentence(
            0, SentenceClass.ASSERTION,
            "The analysis shows hesitation behavior.",
            citations=[citation],
        ),
    ])

    # Should NOT raise
    validator.enforce(envelope)


def test_auto_bracket_after_retries(registry_root: Path):
    """CTX-§4 — auto_bracket_unsourced rewrites uncited ASSERTIONs with [UNSOURCED] prefix."""
    from helpers.citation_validator import CitationValidator

    validator = CitationValidator(registry_root)
    citation = _make_citation("revenge_trade", "entry_delay_ms")

    # Envelope: sentence 0 is cited (keep), sentence 1 is uncited (bracket)
    s0 = _make_sentence(0, SentenceClass.ASSERTION, "Cited claim.", [citation])
    s1 = _make_sentence(1, SentenceClass.ASSERTION, "Uncited claim about behavior.")

    envelope = _make_envelope([s0, s1])
    result = validator.auto_bracket_unsourced(envelope)

    # unsourced_claim_count should be 1
    assert result.unsourced_claim_count == 1

    # sentence 0 unchanged
    assert result.sentences[0].text == "Cited claim."
    assert result.sentences[0].unsourced is False

    # sentence 1 rewritten
    assert result.sentences[1].text == "[UNSOURCED] Uncited claim about behavior."
    assert result.sentences[1].unsourced is True
