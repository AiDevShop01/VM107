"""Phase 58.1 Plan 00 — Wave 0 xfail-strict stubs for 3-copy AST parity.

REQ-58.1-F4 — The ``get_trade_context`` tool ships in THREE copies:
  - VM107/tools/get_trade_context.py (canonical)
  - VM107/agents/strategy_agent/tools/get_trade_context.py (per-agent copy)
  - VM107/agents/idea_agent/tools/get_trade_context.py (per-agent copy)

Plan 02 refactors all three to call the resolver + return NotAvailableResponse
on miss. The 3 copies are NOT subclasses or symlinks — they must be kept in
sync at the source level. These tests run AFTER Plan 02 refactor lands.

Tests graduate from xfail → GREEN in Plan 02.

Wave 0 (Phase 58.1 Plan 00) — these are xfail-strict scaffolding.
See .planning/phases/58.1-legacy-sync-retirement-tool-boundary-cleanup/58.1-VALIDATION.md
for the graduation map (which task in Plan 01/02 makes each test GREEN).
"""
from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason="Wave 0 stub — Plan 02 refactors all 3 copies in lock-step")
def test_all_three_tool_copies_have_identical_resolver_call():
    """AST scan all 3 files; assert the resolver call expression is identical
    (same function name, same single arg, same return-on-miss branch).
    """
    pytest.fail("Plan 02 wires this")


@pytest.mark.xfail(strict=True, reason="Wave 0 stub — Plan 02 imports NotAvailableResponse in each copy")
def test_all_three_copies_import_not_available_response():
    """Each copy contains
    ``from fingpt_core.contracts.agents.not_available import NotAvailableResponse``.
    """
    pytest.fail("Plan 02 wires this")


@pytest.mark.xfail(strict=True, reason="Wave 0 stub — Plan 02 eliminates swallow-and-degrade")
def test_no_silent_swallow_in_any_copy():
    """AST scan: NO copy contains the swallow-and-degrade pattern
    ``except Exception: trade = {}`` (from RESEARCH lines 215-218 — the
    current behavior we are retiring).
    """
    pytest.fail("Plan 02 wires this")
