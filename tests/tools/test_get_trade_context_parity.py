"""Phase 58.1 Plan 02 — graduated GREEN tests for 3-copy AST parity guard.

REQ-58.1-F4 — The ``get_trade_context`` tool ships in THREE files:

  1. VM107/tools/get_trade_context.py
     CANONICAL — the real Tier-2 implementation. Phase 58.1 Task 02-02
     refactored this to call the VM100 resolver and return
     ``NotAvailableResponse`` on miss.

  2. VM107/agents/strategy_agent/tools/get_trade_context.py
     HARD-SCOPE DENIAL STUB — Phase 47.2 lock. The strategy_agent does NOT
     have ``get_trade_context`` in its tool scope. The sibling copy exists
     solely to override the canonical tool via subagents.get_paths()
     priority order — its ``execute()`` raises ``UnauthorizedToolError``.

  3. VM107/agents/idea_agent/tools/get_trade_context.py
     HARD-SCOPE DENIAL STUB — same Phase 47.2 lock for the idea_agent.

The original Wave 0 stub assumed the 3 copies were parallel implementations
that needed to be kept in lock-step. That assumption was WRONG — Phase 47.2's
hard-scope policy (verified by reading the registry YAML's
allowed_agent_profiles + the per-agent stub source) defines copies 2 and 3
as DENIAL stubs. Copying the canonical resolver into them would regress the
hard-scope lock — that would be a Phase 47.2 violation, not a parity win.

Deviation logged in 58.1-02-SUMMARY.md under Rule 1 — plan-body bug.

The graduated tests below enforce the ACTUAL reality:
  - Canonical has resolver call exactly once + NotAvailableResponse import.
  - Both denial stubs preserve UnauthorizedToolError shape.
  - NO copy contains the silent-swallow pattern (the Phase 47.2 thing we
    retired).

Tests graduate from xfail-strict (Plan 00) → GREEN in Plan 02.

See .planning/phases/58.1-legacy-sync-retirement-tool-boundary-cleanup/58.1-VALIDATION.md
for the graduation map.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


# ----------------------------------------------------------------------
# Path discovery — env-driven (no fallback default per MEMORY.md rule)
# ----------------------------------------------------------------------


def _vm107_root() -> Path:
    """Return the VM107 repo root.

    Tries env var first (developer convention), then falls back to the
    test-file-relative path which is robust for the repo's standard layout.
    The fallback is NOT a config default — it's path discovery for a
    git-tracked fixture co-located with the test file.
    """
    env_path = os.environ.get("VM107_ROOT")
    if env_path:
        return Path(env_path)
    # Relative discovery: this test file lives at VM107/tests/tools/, so
    # parent.parent.parent is VM107/.
    return Path(__file__).resolve().parent.parent.parent


_CANONICAL = "tools/get_trade_context.py"
_STRATEGY_STUB = "agents/strategy_agent/tools/get_trade_context.py"
_IDEA_STUB = "agents/idea_agent/tools/get_trade_context.py"

_ALL_COPIES = [_CANONICAL, _STRATEGY_STUB, _IDEA_STUB]
_DENIAL_STUBS = [_STRATEGY_STUB, _IDEA_STUB]

_RESOLVER_PATH_FRAGMENT = "resolve-trade-identity"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _read(rel_path: str) -> str:
    return (_vm107_root() / rel_path).read_text()


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_all_three_files_exist():
    """Pre-condition: all 3 copies exist on disk."""
    for rel in _ALL_COPIES:
        path = _vm107_root() / rel
        assert path.is_file(), f"Missing get_trade_context copy: {path}"


def test_canonical_has_resolver_call_exactly_once():
    """Canonical tool calls /api/journal/internal/resolve-trade-identity exactly once.

    AST-walks the canonical file looking for the resolver path fragment in
    string literals that are NOT inside docstrings. Exactly one occurrence
    is the target — multiple occurrences would suggest copy-paste error;
    zero would mean the resolver was never wired in.

    We discount module/class/function docstrings because human-readable docs
    naturally mention the endpoint name as context.
    """
    src = _read(_CANONICAL)
    tree = ast.parse(src)
    # Collect all docstring node ids so we can exclude them from the count.
    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc_node = ast.get_docstring(node, clean=False)
            if doc_node and node.body and isinstance(node.body[0], ast.Expr):
                docstring_ids.add(id(node.body[0].value))

    code_string_matches = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue
            if _RESOLVER_PATH_FRAGMENT in node.value:
                code_string_matches += 1

    assert code_string_matches == 1, (
        f"Canonical {_CANONICAL} should reference the resolver in code "
        f"exactly once (excluding docstrings); found {code_string_matches}."
    )


def test_canonical_imports_not_available_response():
    """Canonical imports NotAvailableResponse from fingpt_core.

    Phase 47.2 honest-miss lock: the import MUST be present so the tool can
    construct the 6-field envelope on resolver miss.
    """
    src = _read(_CANONICAL)
    expected = (
        "from fingpt_core.contracts.agents.not_available "
        "import NotAvailableResponse"
    )
    assert expected in src, (
        f"Canonical {_CANONICAL} missing NotAvailableResponse import:\n"
        f"expected: {expected}"
    )


def test_denial_stubs_remain_unauthorized_tool_error_shape():
    """Both per-agent sibling copies remain Phase 47.2 HARD-SCOPE denial stubs.

    They must:
      - import UnauthorizedToolError
      - raise it from execute()
    This locks the Phase 47.2 scope decision: strategy_agent + idea_agent
    do NOT have get_trade_context. Copying the canonical resolver into them
    would regress the lock — that would be a Phase 47.2 violation.
    """
    for rel in _DENIAL_STUBS:
        src = _read(rel)
        assert "UnauthorizedToolError" in src, (
            f"Denial stub {rel} no longer references UnauthorizedToolError "
            "— Phase 47.2 hard-scope lock REGRESSED."
        )
        # Source should NOT import NotAvailableResponse (it's not the
        # canonical tool; it never reaches the resolver).
        assert "NotAvailableResponse" not in src, (
            f"Denial stub {rel} should NOT import NotAvailableResponse — "
            "that import indicates someone copied canonical logic into a "
            "hard-scope stub (Phase 47.2 regression)."
        )


def test_no_silent_swallow_in_any_copy():
    """No copy contains the Phase 47.2 silent-swallow pattern.

    The pattern is ``except <ExceptionT>: <name> = {}`` — an empty dict
    assignment inside an except handler that swallows the error and
    degrades to "all None fields" downstream. RESEARCH lines 211-218
    flagged this as the F-4 bug we are retiring.

    Detects via AST walk of all 3 copies.
    """
    for rel in _ALL_COPIES:
        src = _read(rel)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(
                    stmt.value, ast.Dict
                ):
                    if not stmt.value.keys:
                        raise AssertionError(
                            f"{rel}:{stmt.lineno}: silent-swallow pattern "
                            "still present (`<name> = {}` inside except). "
                            "Phase 58.1 F-4 retired this — use "
                            "NotAvailableResponse instead."
                        )


def test_canonical_does_not_use_silent_swallow_as_fallback():
    """Canonical tool's except blocks must produce NotAvailableResponse, not None/{}.

    Quick string-level guard: NotAvailableResponse should appear in the
    canonical at least once (covered by the import test) AND should be
    called/referenced inside the function body. We assert that
    ``_not_available`` is called somewhere in the canonical (the helper
    that wraps NotAvailableResponse construction).
    """
    src = _read(_CANONICAL)
    # The helper name we use in get_trade_context.py.
    assert "_not_available" in src, (
        f"Canonical {_CANONICAL} should define and call the _not_available "
        "helper. If renamed, update this test."
    )
