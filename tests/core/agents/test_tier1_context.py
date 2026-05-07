"""Phase 47.2-01 Wave 0 — xfail stubs for the Tier-1 lightweight context builder.

Target module: core.agents.tier1_context
Plan 07 will graduate these xfail specs to GREEN by shipping
build_tier1_context(journal_id) which:
  - reads VM100 trade data, Postgres last evaluation, Mongo journal metadata
  - returns a curated dict (NOT inline-context driven)
  - degrades gracefully per-section (Postgres down → last_evaluation: None)
  - takes journal_id / trade_id ONLY — never accepts inline context as input
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 implements core/agents/tier1_context.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_build_returns_curated_dict():
    """build_tier1_context returns dict with the locked Tier-1 keys."""
    from core.agents.tier1_context import build_tier1_context  # noqa: F401

    pytest.fail("Wave 0 stub — Plan 07 implements tier1_context.build_tier1_context")


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 implements core/agents/tier1_context.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_partial_when_postgres_unavailable():
    """When Postgres get_last_evaluation raises, builder still returns a dict
    with last_evaluation: None (graceful per-section degradation)."""
    from core.agents.tier1_context import build_tier1_context  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 07 implements tier1_context graceful degradation"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 implements core/agents/tier1_context.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_uses_journal_id_only():
    """Builder takes journal_id (or trade_id) and reads from VM100/Postgres/Mongo —
    it does NOT accept an inline context dict as input (Wave 1 deprecation)."""
    from core.agents.tier1_context import build_tier1_context  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 07 implements tier1_context journal_id-only signature"
    )
