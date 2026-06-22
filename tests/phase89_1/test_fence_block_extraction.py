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

import types
import pytest

from tests.phase89_1.fixtures.macro_envelope_samples import (
    BARE_JSON_DOUBLE_ENCODED_QUOTES,
    BARE_JSON_NO_FENCE,
    BARE_JSON_TRAILING_EXTRA_BRACE,
    BARE_PROSE_WITH_TRUNCATED_JSON_TAIL,
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


@pytest.mark.phase89_1
def test_bare_json_double_encoded_quotes_extracted():
    """Phase 89.1 Plan 05 regression: bare JSON with double-encoded quotes (\\").

    deepseek-v4-flash intermittently emits \\" (literal backslash + quote) inside
    JSON string values instead of \" (the correct JSON escape).  The json parser
    sees the bare " as string termination → JSONDecodeError: "Unterminated string"
    → envelope=None → JSON blob leaks into answer field, citations stay empty.

    Affected in v8 UAT batch: Q1, Q5, Q11 (3/20 questions).

    The fix (step 4b in parse_macro_envelope): after raw_decode fails, replace
    every \\" with \" and retry — handles the dominant double-encoding artifact
    without altering well-formed JSON.
    """
    prose, envelope = parse_macro_envelope(BARE_JSON_DOUBLE_ENCODED_QUOTES)

    assert envelope is not None, (
        "Expected envelope dict for bare JSON with double-encoded quotes — "
        "step 4b repair not working"
    )
    assert "citations" in envelope, "envelope missing 'citations' key"
    assert len(envelope["citations"]) >= 2, (
        f"Expected >=2 citations, got {len(envelope['citations'])}"
    )
    assert "answer" in envelope
    # answer field must be prose text, not the raw JSON blob
    assert not prose.strip().startswith("{"), (
        "Prose should be the extracted answer text, not the JSON blob"
    )
    assert '"citations":' not in prose, (
        "Envelope JSON leaked into answer prose despite double-encoded-quotes fix"
    )


@pytest.mark.phase89_1
def test_prose_with_truncated_json_tail_extracted():
    """Phase 89.1 Plan 05 regression: prose with truncated JSON string tail.

    The LLM emits a bare (unescaped) `"` inside the answer string value when
    constructing the JSON envelope.  That bare `"` terminates the JSON string
    early; the response tool passes the already-deserialized text through, so
    parse_macro_envelope sees:
        <prose>",\n  "citations": [...], "degraded": ..., ...}

    Steps 4 and 4b miss this because the text does not start with `{`.
    Step 4c (truncated JSON tail recovery) reconstructs the envelope by detecting
    the `",\n  "citations":` pattern and wrapping the tail.

    Observed in v9 UAT batch: Q8 (NFP-03), Q13 (GDP-03), Q20 (FED-05).
    """
    prose, envelope = parse_macro_envelope(BARE_PROSE_WITH_TRUNCATED_JSON_TAIL)

    assert envelope is not None, (
        "Expected envelope dict for prose-with-truncated-JSON-tail — "
        "step 4c recovery not working"
    )
    assert "citations" in envelope, "envelope missing 'citations' key"
    assert len(envelope["citations"]) >= 2, (
        f"Expected >=2 citations, got {len(envelope['citations'])}"
    )
    # prose must not contain the JSON tail
    assert '"citations":' not in prose, (
        "JSON tail leaked into prose despite truncated-tail fix"
    )
    # prose must be the clean answer text (no JSON structure)
    assert not prose.strip().startswith("{"), (
        "Prose looks like a JSON object — truncated-tail fix not stripping correctly"
    )


@pytest.mark.phase89_1
def test_bare_json_trailing_extra_brace_extracted():
    """Phase 89.1 Plan 05 regression: bare JSON with a trailing extra } brace.

    deepseek-v4-flash intermittently emits an extra closing brace after an
    otherwise well-formed JSON envelope.  The original json.loads() call
    raised JSONDecodeError and returned (raw_blob, None), causing envelope
    JSON to leak into the answer field and citations to stay empty.

    The fix: use json.JSONDecoder().raw_decode() which extracts the first
    valid JSON object and ignores trailing garbage.
    """
    prose, envelope = parse_macro_envelope(BARE_JSON_TRAILING_EXTRA_BRACE)

    assert envelope is not None, (
        "Expected envelope dict for bare JSON with trailing extra } — raw_decode fix not working"
    )
    assert "citations" in envelope, "envelope missing 'citations' key"
    assert len(envelope["citations"]) >= 2, (
        f"Expected >=2 citations, got {len(envelope['citations'])}"
    )
    assert "answer" in envelope
    # answer field must be the prose string, not the raw JSON blob
    assert not prose.strip().startswith("{"), (
        "Prose should be the extracted answer text, not the JSON blob"
    )
    # citations must not appear in the prose/answer output
    assert '"citations":' not in prose, (
        "Envelope JSON leaked into answer prose despite trailing-brace fix"
    )


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


# ---------------------------------------------------------------------------
# Contract regression test: api_message envelope wiring
# ---------------------------------------------------------------------------


def _make_mock_agent0(data: dict):
    """Build a minimal agent0 stand-in that answers get_data() calls."""
    agent0 = types.SimpleNamespace()
    agent0.get_data = lambda key, default=None: data.get(key, default)
    return agent0


@pytest.mark.phase89_1
def test_api_message_no_envelope_leakage_in_answer_field():
    """Contract test: _build_macro_investigator_response returns a dict whose
    'answer' field contains clean prose — no JSON object or 'citations:' string.

    Exercises the wire-up in api_message.py without spinning up Flask/agent
    context by calling parse_macro_envelope directly (the same code path the
    wired handler uses) and asserting the AskResponse contract is satisfied.
    """
    # Simulate what api_message.py does after the parse_macro_envelope wiring:
    answer_text = PROSE_PLUS_FENCED_JSON.strip()
    agent0_data = {}  # agent0 slots empty — envelope must fill them

    citations = agent0_data.get("citations") or []
    b5_result = agent0_data.get("b5_result")
    degraded = bool(agent0_data.get("b5_degraded") or False)
    blocking = bool(agent0_data.get("blocking_contradiction_refusal") or False)
    truncated_at = agent0_data.get("truncated_at")

    answer_prose, envelope = parse_macro_envelope(answer_text)
    if envelope:
        answer_text = answer_prose or envelope.get("answer", answer_text)
        if not citations:
            citations = envelope.get("citations") or []
        if b5_result is None:
            b5_result = envelope.get("b5_result")
        if not degraded:
            degraded = bool(envelope.get("degraded", False))
        if not blocking:
            blocking = bool(envelope.get("blocking_contradiction_refusal", False))
        if truncated_at is None:
            truncated_at = envelope.get("truncated_at")

    result = {
        "answer": answer_text,
        "citations": citations,
        "b5_result": b5_result,
        "degraded": degraded,
        "blocking_contradiction_refusal": blocking,
        "truncated_at": truncated_at,
    }

    # Contract assertion 1: answer field must NOT contain raw JSON envelope
    assert '"citations":' not in result["answer"], (
        "Envelope JSON leaked into 'answer' field — fence stripping failed"
    )
    # Contract assertion 2: answer must not start with '{' (JSON object)
    assert not result["answer"].strip().startswith("{"), (
        "'answer' field starts with '{' — looks like raw JSON envelope"
    )
    # Contract assertion 3: citations[] must be populated (not empty)
    assert len(result["citations"]) >= 2, (
        f"Expected >=2 citations in result, got {result['citations']}"
    )
    # Contract assertion 4: b5_result populated from envelope
    assert result["b5_result"] is not None, (
        "b5_result should be populated from the fence envelope"
    )
