"""Macro investigator envelope parser — Phase 89.1 Plan 01.

Pure function that extracts the trailing fenced JSON envelope from a
macro_investigator answer and returns (answer_prose, envelope_dict_or_none).

Fixes the fence-block citation extraction gap documented in:
  .planning/phases/89-macro-intelligence-workbench-investigation-counterfactual-
  contradiction-discovery/89-WIRING-RCA-HANDOFF.md  (Gap #1 — REQ-89-9.1)

The bug being fixed: api/api_message.py called json.loads(answer_text) on the
FULL text. The prose preamble makes the text invalid JSON → parse always fails
→ citations[] stays empty → REQ-89-9 hallucination gate has no chips to review.

Envelope shapes handled:
  (a) Prose followed by a trailing ```json fenced block (standard model output)
  (b) Prose followed by a trailing ```JSON (uppercase tag) fenced block
  (c) Prose followed by a trailing ``` (bare, no language tag) fenced block
  (d) Bare JSON with no fence at all (backward-compat, pre-89.1 happy path)

Failure-mode policy:
  - Unclosed fence → return (full_text, None)    — no partial leakage
  - Malformed JSON → return (prose_before_fence, None)  — fence stripped, no leak
  - No fence / no JSON → return (full_text, None)
"""
from __future__ import annotations

import json
import re

# Matches a TRAILING fenced JSON block at the end of the string.
# Groups:
#   body — the raw JSON text between the opening and closing fences
#
# Notes on the pattern:
#   - `(?:json|JSON|Json)?` accepts any common capitalisation of the language tag,
#     or no tag at all (bare ``` fences).
#   - `\s*\n?` allows optional whitespace / newline between the opening fence line
#     and the JSON body.
#   - `re.DOTALL` lets `.` match newlines inside the JSON body.
#   - `\s*$` anchors to the end of the string so we only strip a TRAILING fence.
#     Inline code fences in the prose (e.g. `python ...`) are left intact.
_FENCE_RE = re.compile(
    r"```(?:json|JSON|Json)?\s*\n?(?P<body>.*?)\n?\s*```\s*$",
    re.DOTALL,
)

# Matches an UNCLOSED fence opening — an opening ``` that has no matching
# closing ``` at or after it.  Used to detect the unclosed-fence failure mode
# so we can strip the partial JSON body rather than returning it verbatim.
_UNCLOSED_FENCE_RE = re.compile(
    r"(?P<prose>.*?)```(?:json|JSON|Json)?\s*\n?(?P<body>.+)$",
    re.DOTALL,
)


def parse_macro_envelope(answer_text: str) -> tuple[str, dict | None]:
    """Extract a trailing fenced JSON envelope from a macro_investigator answer.

    Args:
        answer_text: The raw answer text returned by the model.  May contain
            prose, inline citation chips, and optionally a trailing fenced
            JSON envelope.

    Returns:
        A ``(answer_prose, envelope)`` tuple where:
        - ``answer_prose`` is the human-readable portion (fence stripped).
        - ``envelope`` is the parsed dict, or ``None`` if extraction failed.

    Guarantee: The returned ``answer_prose`` will NEVER contain the fence
    body, even when JSON parsing fails — preventing envelope JSON from leaking
    into the user-facing answer field.
    """
    if not answer_text:
        return (answer_text or ""), None

    # Step 1: Search for a trailing fenced block.
    match = _FENCE_RE.search(answer_text)

    if match:
        body = match.group("body")
        fence_start = match.start()
        prose = answer_text[:fence_start].rstrip()

        # Step 2a: Fence found — try to parse the body as JSON.
        try:
            envelope = json.loads(body)
            if isinstance(envelope, dict):
                return prose, envelope
            # Unexpected non-dict JSON inside the fence — strip fence, no envelope.
            return prose, None
        except (ValueError, TypeError):
            # Step 2b: Fence found but JSON is malformed — strip fence body,
            # return prose only.  This prevents the malformed JSON from leaking
            # into the user-facing answer field.
            return prose, None

    # Step 3: No trailing fence, but check for an UNCLOSED fence opening.
    # If found, strip the partial JSON body to prevent leakage.
    unclosed_match = _UNCLOSED_FENCE_RE.search(answer_text)
    if unclosed_match:
        # Only treat as unclosed if the body portion looks like JSON content
        # (starts with { or [ after optional whitespace).
        body_candidate = unclosed_match.group("body").strip()
        if body_candidate.startswith(("{", "[")):
            prose_before = unclosed_match.group("prose").rstrip()
            return prose_before, None

    # Step 4: No fence found — try backward-compat bare-JSON path.
    # Phase 89.1 Plan 05 fix: LLM intermittently emits extra trailing `}` after the
    # closing brace of a well-formed JSON envelope (non-deterministic generation
    # artifact from deepseek-v4-flash). `json.loads()` rejects the malformed string,
    # causing envelope=None → citations stay empty → leakage into answer field.
    # Fix: use `json.JSONDecoder().raw_decode()` which extracts the first complete JSON
    # object and ignores any trailing garbage, making the parser robust to this artifact.
    stripped = answer_text.strip()
    try:
        decoder = json.JSONDecoder()
        envelope, end_idx = decoder.raw_decode(stripped)
        if isinstance(envelope, dict) and "answer" in envelope:
            # Pure JSON envelope with no prose prefix (possibly trailing garbage ignored).
            prose = envelope.get("answer", "")
            return prose, envelope
    except (ValueError, TypeError):
        pass

    # Step 4b: raw_decode failed — try repairing double-encoded JSON quotes.
    # deepseek-v4-flash intermittently emits \\" (a literal backslash followed by a
    # quote character) inside JSON string values instead of \" (the correct JSON
    # escape sequence for an embedded quote).  When this artifact is present, the
    # JSON parser sees the bare `"` after `\\` as a string-termination character,
    # causing an "Unterminated string" JSONDecodeError.
    #
    # Observed in v8 UAT batch: Q1, Q5, Q11 all ended with `\\"key\\": value}`
    # where `\\"` prematurely closed the answer string.
    #
    # Fix: replace every `\\"` (four chars: backslash backslash quote in the raw
    # Python string, i.e. the two-char sequence backslash+quote in the text)
    # with `\"` (the standard JSON escape) and retry raw_decode.
    try:
        repaired = stripped.replace('\\\\"', '\\"')
        if repaired != stripped:  # only retry if the substitution changed anything
            decoder2 = json.JSONDecoder()
            envelope, end_idx = decoder2.raw_decode(repaired)
            if isinstance(envelope, dict) and "answer" in envelope:
                prose = envelope.get("answer", "")
                return prose, envelope
    except (ValueError, TypeError):
        pass

    # Step 5: No fence, no parseable JSON — return full text as prose.
    return answer_text, None
