"""Phase 47.2-01 Wave 0 — xfail stubs for the chat handler Tier-1 integration.

Target module: api.v1.trades.ai.chat
Plan 07 will graduate these xfail specs to GREEN by:
  - making the chat handler IGNORE inline `context` payload from VM100
  - calling build_tier1_context(journal_id) server-side instead
  - threading the Tier-1 dict into _build_user_prompt
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 deprecates inline context; chat reads Tier-1 from journal_id",
    strict=False,
)
@pytest.mark.asyncio
async def test_inline_context_ignored():
    """POST chat with inline {context: {instrument: 'FAKE'}}. Patch
    build_tier1_context → {instrument: 'REAL', ...}. _build_user_prompt
    must receive the Tier-1 dict (REAL), not the inline FAKE."""
    from api.v1.trades.ai.chat import process  # noqa: F401

    pytest.fail("Wave 0 stub — Plan 07 wires chat handler to Tier-1 context")


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 deprecates inline context; chat reads Tier-1 from journal_id",
    strict=False,
)
@pytest.mark.asyncio
async def test_inline_context_not_passed_to_prompt():
    """Inside process(), the value bound to `context` is the result of
    build_tier1_context(journal_id), NOT input.get('context')."""
    from api.v1.trades.ai.chat import process  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 07 binds context = build_tier1_context(journal_id)"
    )
