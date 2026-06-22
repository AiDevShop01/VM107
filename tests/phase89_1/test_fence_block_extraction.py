"""Phase 89.1 Plan 01 — fence-block envelope extraction regression tests.

Tests the parse_macro_envelope() pure function that replaces the broken
json.loads(answer_text) call in api/api_message.py.

The original bug: when the model emits "prose followed by ```json fenced envelope"
(its standard output shape), json.loads() fails because prose makes the text
invalid JSON. Result: citations[] stays empty and the envelope JSON leaks into
the user-facing answer field.

See: .planning/phases/89.1-.../89.1-01-wave1-fence-block-citation-extraction-PLAN.md
"""
from __future__ import annotations

import pytest

from tests.phase89_1.fixtures.macro_envelope_samples import (
    BARE_JSON_NO_FENCE,
    FENCE_MALFORMED_JSON,
    NO_FENCE_NO_JSON,
    PROSE_PLUS_FENCED_JSON,
    PROSE_PLUS_FENCED_JSON_UPPERCASE,
    PROSE_PLUS_FENCED_NO_LANG,
    UNCLOSED_FENCE,
)

# The parser module does not exist yet — import will fail (RED phase).
from helpers.macro_envelope_parser import parse_macro_envelope


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.phase89_1
def test_prose_plus_fenced_json_extracts_envelope():
    """Standard ```json fence: prose is returned clean, envelope is parsed."""
    prose, envelope = parse_macro_envelope(PROSE_PLUS_FENCED_JSON)

    assert envelope is not None, "Expected envelope dict, got None"
    # Prose must not contain the fence
    assert "```json" not in prose, "Fence block leaked into prose"
    assert "```" not in prose, "Fence delimiter leaked into prose"
    # Citations array must have content
    assert "citations" in envelope, "envelope missing 'citations' key"
    assert len(envelope["citations"]) >= 2, (
        f"Expected >=2 citations, got {len(envelope['citations'])}"
    )
    # Envelope keys are present
    assert "b5_result" in envelope
    assert "degraded" in envelope
    assert "blocking_contradiction_refusal" in envelope
    assert "truncated_at" in envelope


@pytest.mark.phase89_1
def test_uppercase_language_tag_supported():
    """```JSON (uppercase) fence: treated same as ```json."""
    prose, envelope = parse_macro_envelope(PROSE_PLUS_FENCED_JSON_UPPERCASE)

    assert envelope is not None, "Expected envelope dict for uppercase JSON tag"
    assert "```JSON" not in prose, "Uppercase fence leaked into prose"
    assert "```" not in prose, "Fence delimiter leaked into prose"
    assert len(envelope["citations"]) >= 2


@pytest.mark.phase89_1
def test_bare_fence_no_language_tag_supported():
    """Bare ``` fence (no language tag): parsed as JSON envelope."""
    prose, envelope = parse_macro_envelope(PROSE_PLUS_FENCED_NO_LANG)

    assert envelope is not None, "Expected envelope dict for bare ``` fence"
    assert "```" not in prose, "Fence delimiter leaked into prose"
    assert len(envelope["citations"]) >= 2


@pytest.mark.phase89_1
def test_bare_json_no_fence_backward_compat():
    """Bare JSON (no fence) — the pre-89.1 happy path — still works."""
    prose, envelope = parse_macro_envelope(BARE_JSON_NO_FENCE)

    assert envelope is not None, "Expected envelope dict for bare JSON input"
    assert "citations" in envelope, "envelope missing 'citations' key"
    assert len(envelope["citations"]) >= 2
    assert "answer" in envelope


# ---------------------------------------------------------------------------
# Failure-mode tests — parser must return (full_text_or_prose, None)
# ---------------------------------------------------------------------------


@pytest.mark.phase89_1
def test_pure_prose_returns_none_envelope():
    """Pure prose answer (no JSON) — envelope is None, full text returned."""
    prose, envelope = parse_macro_envelope(NO_FENCE_NO_JSON)

    assert envelope is None, f"Expected None envelope for pure prose, got {envelope}"
    assert prose == NO_FENCE_NO_JSON, (
        "Pure prose answer text should be returned unchanged"
    )


@pytest.mark.phase89_1
def test_unclosed_fence_returns_none_no_leak():
    """Unclosed fence (missing closing ```) — envelope is None, no leakage."""
    prose, envelope = parse_macro_envelope(UNCLOSED_FENCE)

    assert envelope is None, f"Expected None for unclosed fence, got {envelope}"
    # Critical: the envelope JSON must NOT leak into the returned text
    assert '"citations":' not in prose, (
        "Envelope JSON content leaked into answer from unclosed fence"
    )


@pytest.mark.phase89_1
def test_malformed_json_returns_none_no_leak():
    """Fence present but JSON is malformed (trailing comma) — envelope is None,
    fence body is stripped from the returned prose (no leakage)."""
    prose, envelope = parse_macro_envelope(FENCE_MALFORMED_JSON)

    assert envelope is None, f"Expected None for malformed JSON, got {envelope}"
    # Critical: malformed fence body must NOT leak into the returned answer string
    assert '"citations":' not in prose, (
        "Malformed envelope JSON content leaked into answer"
    )
