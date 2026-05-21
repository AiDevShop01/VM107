"""Phase 62.1 Plan 04 — BUG-19 unit tests: json_parse_dirty tool-request preference.

BUG-19 root cause:
    ``extract_json_object_string`` (used inside ``json_parse_dirty``) is naive:
    it grabs from the first ``{`` to the LAST ``}``.  When DeepSeek emits a
    markdown audit report containing embedded JSON snippets like
    ``{"score": null, "liquidity_score": null}`` followed by an actual tool call
    ``{"tool_name": "response", "tool_args": {...}}``, the extractor returns a
    giant mashed substring and DirtyJson picks up the embedded scoring JSON (the
    first parseable dict) — not the tool call.  The validator then correctly
    rejects: "Tool request must have a tool_name (type string) field".

Fix (BUG-19):
    ``json_parse_dirty`` must scan the response for ALL top-level JSON objects
    and prefer the FIRST one that contains ``tool_name`` (string) or ``tool``
    (string) as a top-level key.  Only fall back to the old naïve extraction if
    no tool-request-shaped object is found.

Tests (cases 1-3 must PASS before fix; cases 4-7 FAIL before fix, all PASS after):
    1. Pure tool call (no prose)                 → returns it                   [pre-fix PASS]
    2. Embedded null-score JSON, no tool call    → returns the embedded JSON    [pre-fix PASS]
    3. Empty/None input                          → returns None                 [pre-fix PASS]
    4. Markdown + embedded JSON + tool call end  → returns tool call            [pre-fix FAIL]
    5. Tool alias ``tool`` instead of ``tool_name``  → found                   [pre-fix FAIL]
    6. Multiple tool-call-shaped objects         → returns the first            [pre-fix FAIL]
    7. Real-style captured DeepSeek body          → returns the tool call       [pre-fix FAIL]
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
from helpers.extract_tools import json_parse_dirty


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_EMBEDDED_SCORING_JSON = '{"score": null, "liquidity_score": null, "momentum_score": null}'

_TOOL_CALL_CANONICAL = '{"tool_name": "response", "tool_args": {"text": "Trade analysis complete."}}'
_TOOL_CALL_ALIAS = '{"tool": "write_file", "args": {"path": "/tmp/out.txt", "content": "done"}}'

_MARKDOWN_REPORT_WITH_TOOL_CALL = f"""\
## Audit Report

| Field | Value |
|---|---|
| Symbol | EURUSD |
| Score | null |

Embedded scoring snapshot: {_EMBEDDED_SCORING_JSON}

Further analysis suggests the trade lacked a clear edge.

{_TOOL_CALL_CANONICAL}
"""

_MARKDOWN_REPORT_WITH_ALIAS_TOOL_CALL = f"""\
## Audit Report

Some prose about the trade.

Embedded null scores: {_EMBEDDED_SCORING_JSON}

{_TOOL_CALL_ALIAS}
"""

# A realistic DeepSeek-style body: markdown table, embedded partial JSON,
# then the actual tool call at the very end.
_REAL_DEEPSEEK_STYLE_BODY = """\
Based on my analysis of the trade log, here is my structured evaluation:

## Evaluation Summary

| Metric | Value |
|--------|-------|
| Entry Quality | Poor |
| Exit Quality | Fair |
| Overall Score | Needs Improvement |

### Scoring Breakdown

The following scores reflect the trade quality across dimensions:

```json
{"score": null, "liquidity_score": null, "momentum_score": null, "volatility_score": null}
```

### Key Observations

1. The entry was premature relative to the momentum signal.
2. The exit captured only 30% of the available move.

### Recommendation

Consider tightening entry criteria to require confirmation from at least two indicators.

{"tool_name": "response", "tool_args": {"text": "Evaluation complete. The trade showed premature entry and suboptimal exit timing. Recommend reviewing entry criteria."}}
"""


# ---------------------------------------------------------------------------
# Case 1 — Pure tool call, no prose (regression: must still work pre-fix)
# ---------------------------------------------------------------------------

def test_pure_tool_call_returns_tool_call():
    """A bare JSON tool call with no surrounding markdown is parsed correctly.

    This is the happy path that already works — regression lock.
    """
    result = json_parse_dirty(_TOOL_CALL_CANONICAL)
    assert isinstance(result, dict)
    assert result.get("tool_name") == "response"
    assert "tool_args" in result


# ---------------------------------------------------------------------------
# Case 2 — Embedded null-score JSON with NO tool call (regression: fallback)
# ---------------------------------------------------------------------------

def test_embedded_null_json_no_tool_call_returns_embedded_json():
    """When no tool-request-shaped object exists, fall back to original behavior.

    The embedded scoring JSON has no ``tool_name``/``tool`` key, so the new
    scanner finds nothing and the old path runs — returning the embedded dict.
    """
    result = json_parse_dirty(_EMBEDDED_SCORING_JSON)
    assert isinstance(result, dict)
    assert "score" in result


# ---------------------------------------------------------------------------
# Case 3 — Empty / None input (regression: must return None)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", [None, "", "   ", 42, []])
def test_empty_or_non_string_returns_none(bad_input):
    """Non-string or empty inputs always return None — regression lock."""
    assert json_parse_dirty(bad_input) is None


# ---------------------------------------------------------------------------
# Case 4 — Markdown report with embedded JSON + tool call at the end
# ---------------------------------------------------------------------------

def test_markdown_with_embedded_json_prefers_tool_call():
    """BUG-19 primary fix: markdown containing embedded scoring JSON followed
    by a canonical tool call returns the tool call, not the embedded dict.

    This test FAILS before the BUG-19 fix.
    """
    result = json_parse_dirty(_MARKDOWN_REPORT_WITH_TOOL_CALL)
    assert isinstance(result, dict), f"Expected dict, got: {type(result)!r} — value: {result!r}"
    assert result.get("tool_name") == "response", (
        f"Expected tool_name='response', got: {result!r}"
    )
    assert "tool_args" in result


# ---------------------------------------------------------------------------
# Case 5 — Tool alias ``tool``/``args`` instead of ``tool_name``/``tool_args``
# ---------------------------------------------------------------------------

def test_alias_tool_key_is_found_in_markdown():
    """BUG-19 fix must also match the ``tool``/``args`` alias form.

    DeepSeek sometimes emits ``{"tool": "...", "args": {...}}`` rather than the
    canonical form.  The scanner must treat ``tool`` (string value) as a
    tool-request signal.

    This test FAILS before the BUG-19 fix.
    """
    result = json_parse_dirty(_MARKDOWN_REPORT_WITH_ALIAS_TOOL_CALL)
    assert isinstance(result, dict), f"Expected dict, got: {type(result)!r} — value: {result!r}"
    # Either "tool" or "tool_name" key should be present with a string value
    tool_name = result.get("tool_name") or result.get("tool")
    assert isinstance(tool_name, str) and tool_name, (
        f"Expected string tool name, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Case 6 — Multiple tool-call-shaped objects: return the first
# ---------------------------------------------------------------------------

def test_multiple_tool_calls_returns_first():
    """When multiple tool-call-shaped objects exist, return the FIRST one.

    This test FAILS before the BUG-19 fix (because the old code returns the
    first ``{`` to the last ``}`` which mashes both objects together).
    """
    content = (
        '{"tool_name": "read_file", "tool_args": {"path": "/tmp/a.txt"}} '
        'some prose '
        '{"tool_name": "write_file", "tool_args": {"path": "/tmp/b.txt", "content": "x"}}'
    )
    result = json_parse_dirty(content)
    assert isinstance(result, dict)
    assert result.get("tool_name") == "read_file", (
        f"Expected first tool call (read_file), got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Case 7 — Real-style captured DeepSeek body (regression against BUG-19)
# ---------------------------------------------------------------------------

def test_real_deepseek_style_body_returns_tool_call():
    """Realistic DeepSeek response body: markdown, code-fenced embedded JSON,
    prose, then canonical tool call at the end → must return the tool call.

    This is the actual failure pattern observed in the 6 failing mentor pipeline
    runs (run IDs 41ee0e63, 5a2e5809, etc.) that prompted BUG-19.

    This test FAILS before the BUG-19 fix.
    """
    result = json_parse_dirty(_REAL_DEEPSEEK_STYLE_BODY)
    assert isinstance(result, dict), f"Expected dict, got: {type(result)!r}"
    assert result.get("tool_name") == "response", (
        f"Expected tool_name='response', got: {result!r}"
    )
    tool_args = result.get("tool_args")
    assert isinstance(tool_args, dict), f"Expected tool_args dict, got: {tool_args!r}"
    assert "text" in tool_args
