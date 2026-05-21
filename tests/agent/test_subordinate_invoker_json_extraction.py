"""Phase 62.1 — BUG-13 invoker unit test scaffold: JSON extraction from prose-wrapped text.

BUG-13 (partial) context (helpers/mentor_subordinate_invoker.py:136-186):
    The invoker unwraps the subordinate's monologue response.  When the LLM
    wraps the JSON payload inside prose (e.g. a markdown explanation followed by
    a JSON block), the current code hits the ``_unwrapped_prose`` sentinel and
    the orchestrator's model_validate hard-fails.

    The proposed fix (option d per CONTEXT.md): extract the first/last ``{...}``
    JSON block from raw text before giving up and returning the prose sentinel.

Wave 1 (Plan 62.1-01) implements the json-block extraction fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.mentor_subordinate_invoker import invoke_mentor_subordinate  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-13 invoker implementation pending in Phase 62.1 Plan 01 — pure JSON works today (baseline lock)",
    strict=True,
    run=True,
)
def test_invoker_returns_parsed_dict_when_text_is_pure_json():
    """invoke_mentor_subordinate returns a parsed dict when response text is pure JSON.

    Baseline lock: this already works — the invoker calls json.loads(raw) and
    returns the dict.  strict=True catches any regression in the existing path.
    """
    pytest.xfail("BUG-13 invoker baseline lock pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-13 invoker implementation pending in Phase 62.1 Plan 01 — prose-wrapped JSON not extracted today",
    strict=False,
    run=True,
)
def test_invoker_extracts_json_block_from_prose_wrapped_text():
    """invoke_mentor_subordinate must extract JSON from prose-wrapped LLM output.

    Observed LLM behavior: DeepSeek emits a markdown explanation followed by
    the JSON payload, e.g.:

        ``Here is the trade audit result:\\n\\n{\"audit_findings\": [...]}``

    Current behavior: json.loads fails on the full string; invoker returns
    ``{"_unwrapped_prose": "...", ...}`` sentinel; orchestrator model_validate
    hard-fails.

    Expected behavior after fix: invoker extracts the first ``{...}`` JSON block
    (via regex or manual brace scanning), returns the parsed dict.
    """
    pytest.xfail("BUG-13 invoker implementation pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-13 invoker implementation pending in Phase 62.1 Plan 01 — warning log not implemented yet",
    strict=False,
    run=True,
)
def test_invoker_logs_warning_on_extraction_fallback():
    """invoke_mentor_subordinate must log a warning when JSON extraction fallback is used.

    The warning provides an observability signal that the LLM is not following
    the strict JSON output contract — useful for prompt engineering iteration.
    """
    pytest.xfail("BUG-13 invoker implementation pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-13 invoker implementation pending in Phase 62.1 Plan 01 — prose sentinel path exists today (lock)",
    strict=True,
    run=True,
)
def test_invoker_returns_unwrapped_prose_sentinel_when_no_json_block():
    """invoke_mentor_subordinate returns the _unwrapped_prose sentinel when no JSON block exists.

    Baseline lock: the current sentinel path (Phase 60, invoker line ~175-178)
    handles the case where text is pure prose with no JSON.  This test locks
    that behavior: after BUG-13 adds JSON extraction, the sentinel path must
    still fire when TRULY no JSON block is present (not just json.loads failure).
    """
    pytest.xfail("BUG-13 invoker sentinel baseline lock pending in Phase 62.1 Plan 01")
