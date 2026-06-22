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
  (e) Prose with a truncated-JSON tail: the LLM embedded a bare " inside the
      `answer` string value, which closed the string early.  The remaining JSON
      keys (citations, degraded, …) appear as a raw fragment appended to the
      prose text.  The shape is:  <prose>",\n  "citations": [...], ...}

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

# Matches the "truncated JSON string tail" artifact observed in v9/v10 UAT batches.
#
# The LLM constructs its `text` arg as a JSON object {"answer": "...", "citations": [...]}.
# Inside the `answer` string value it occasionally emits a bare (unescaped) `"` character,
# which terminates the string early.  The `response` tool receives the JSON-deserialized
# value, so by the time parse_macro_envelope sees it the Python string looks like:
#
#   (variant A — prose-first, v9 shape):
#     <prose text ending with some word>",
#       "citations": [ { "citation_id": "...", ... }, ... ],
#       "degraded": <bool>, "blocking_contradiction_refusal": <bool>
#     }
#
#   (variant B — bare-JSON-first, v10 shape):
#     {"answer": "<prose ends here>", "citations": [...], ...}
#     where the answer string was terminated early so raw_decode fails
#
# For variant A the text does NOT start with `{`; for variant B it DOES.
# Both are handled by _try_tail_recovery() via the shared regex below.
#
# Regex: searches for the LAST occurrence of `"` followed by a `, ... "citations":` pattern
# and captures:
#   prose  — everything before that `"`
#   tail   — `,\s*"citations": [...],...}` (the JSON fragment after the rogue quote)
#
# Changes from v9:
#   - Removed the mandatory `\n` before `"citations"` (v10 Q15 had inline `, "citations":`)
#   - Made the pattern search within the full text (not just at `^`) to handle bare-JSON-
#     prefixed shapes (v10 Q7/Q9 start with `{"answer": "`)
_TRUNCATED_JSON_TAIL_RE = re.compile(
    r'(?P<prose>.*?)"(?P<tail>,\s*"citations"\s*:.+}\s*)$',
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

    # Step 4c: Truncated JSON string tail recovery.
    # The LLM sometimes emits a bare (unescaped) `"` inside the `answer` string value
    # of the JSON envelope it passes to the `response` tool.  That bare `"` terminates
    # the JSON string early; the `response` tool then deserializes the `text` arg and
    # passes the result to parse_macro_envelope.  The resulting Python string looks like:
    #
    #   (variant A — v9 shape, text does NOT start with `{`):
    #     <prose>",\n  "citations": [...], "degraded": ..., ...}
    #
    #   (variant B — v10 shape, text starts with `{`):
    #     {"answer": "<prose ends here>", "citations": [...], ...}
    #     where raw_decode failed because the answer string was terminated early
    #
    #   (variant C — v10 Q15 shape, inline tail, no newline before "citations":):
    #     <prose>", "citations": [...], ...}   ← no \n before "citations"
    #
    # Steps 4/4b handle the trailing-garbage and double-encoding cases but not
    # bare-quote termination.  Step 4c detects the `"citations":` tail by regex,
    # extracts the prose before the rogue `"`, reconstructs a parseable envelope,
    # and returns clean prose + envelope.
    #
    # Observed: v9 Q8/Q13/Q20 (variant A), v10 Q7/Q9 (variant B), v10 Q15 (variant C).
    tail_match = _TRUNCATED_JSON_TAIL_RE.search(stripped)
    if tail_match:
        # For variant B (text starts with `{`), the "prose" group will contain the
        # `{"answer": "` prefix plus the prose content.  We need to strip that prefix
        # to get the actual prose text.
        prose_raw = tail_match.group("prose")
        # Strip leading {"answer": " prefix if present (bare-JSON variant B/C from
        # a well-formed outer JSON object whose answer string was terminated early).
        prose_before = re.sub(r'^\{[^{]*"answer"\s*:\s*"', '', prose_raw).rstrip()
        if not prose_before:
            prose_before = prose_raw.rstrip()

        tail_fragment = tail_match.group("tail")  # ,\s*"citations": [...], ...}
        # Build a synthetic JSON envelope: {"answer": "<prose>", "citations": [...], ...}
        # Strip the leading comma from tail_fragment and wrap in { }.
        # Also handle the case where the tail itself contains double-encoded JSON
        # (e.g. v10 Q7/Q9: the citations array uses \\" instead of \" because the whole
        # JSON was double-serialised).  If the first reconstruction attempt fails, retry
        # after replacing \\" → \" in the tail fragment.
        tail_stripped = tail_fragment.lstrip(",").strip()  # "citations": [...], ...}
        # Strip outer-wrapper garbage: v10 Q9 ends with `false}"\n    }\n}`
        # where there's an extra nested `}\n}` after the envelope.  Strip anything after
        # the last `}` that closes the envelope (the part matching `false}`).
        tail_stripped = re.sub(r'(false|true)\s*\}\s*"?[^"]*\}\s*\}?\s*$', r'\1}', tail_stripped)

        # Try three variants of the tail:
        #   1. As-is (v9/v10-Q15 shape: properly encoded tail)
        #   2. With \\" → \" repair (step-4b-style fix for double-encoded tail)
        #   3. With \" → " unescaping (v10-Q7/Q9 shape: tail uses backslash-quote for keys)
        for attempt_tail in (
            tail_stripped,
            tail_stripped.replace('\\\\"', '\\"'),
            tail_stripped.replace('\\"', '"'),
        ):
            synthetic_json = '{"answer": ' + json.dumps(prose_before) + ", " + attempt_tail
            try:
                envelope = json.loads(synthetic_json)
                if isinstance(envelope, dict) and "citations" in envelope:
                    prose = envelope.get("answer", prose_before)
                    return prose, envelope
            except (ValueError, TypeError):
                continue

        # All reconstruction attempts failed — at minimum strip the JSON tail to prevent leakage.
        return prose_before, None

    # Step 5: No fence, no parseable JSON — return full text as prose.
    return answer_text, None
