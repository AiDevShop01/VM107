"""Discoverability + surface tests for the LIVE P4 SearchKnowledgeTool.

Phase 138 (P6 / Wave 0) REPOINT: this test previously imported the superseded
pre-P4 duplicate under ``tools/qdrant/`` that Wave A deletes (RESEARCH §1: that
duplicate is shadowed at ``get_tool`` by the flat ``tools/search_knowledge.py``
lookup, and this test was its only non-runtime reference). The old assertions exercised
that dead module's private helpers (``_validate_request`` / ``_call_vm`` /
``_validate_response`` / ``_format_response``), which do NOT exist on the P4 successor
(whose surface is ``execute`` + ``_degraded_response`` / ``_vm101_search`` /
``_format_local_hits``), so they cannot be honestly mapped.

Per the plan, they are replaced with a minimal import-and-resolve assertion proving
the LIVE ``tools/search_knowledge.py`` (Phase 136 / P4, D-02/D-03) imports and its Tool
class is discoverable via the exact mechanism ``Agent.get_tool`` uses
(``helpers.extract_tools.load_classes_from_file``). This keeps coverage on the P4
successor and decouples the suite from the Wave-A delete target — the deletion becomes
coupling-free.
"""
from __future__ import annotations

import os
from pathlib import Path

# The P4 tool fail-fast-reads VM101_KB_SEARCH_URL at import (D-04). The VM101 HTTP
# fallback is OFF by default, so this dummy is never dialed — it only lets the
# discoverability import succeed outside a fully-env'd container (mirrors the
# tests/tools/test_phase60_*.py os.environ.setdefault idiom). Leak-safe: no real host.
os.environ.setdefault("VM101_KB_SEARCH_URL", "http://test-vm101:8000/api/v1/knowledge/search")

from helpers.extract_tools import load_classes_from_file
from helpers.tool import Tool

# tests/tools/ -> two levels up == VM107 root (== /a0 in-container).
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_P4_TOOL_PATH = _VM107_ROOT / "tools" / "search_knowledge.py"


def test_p4_search_knowledge_module_imports():
    """The LIVE P4 tools/search_knowledge.py imports and exposes a Tool subclass."""
    from tools.search_knowledge import SearchKnowledgeTool

    assert issubclass(SearchKnowledgeTool, Tool), "SearchKnowledgeTool must be a Tool subclass"


def test_p4_search_knowledge_discoverable_by_get_tool_mechanism():
    """load_classes_from_file (the get_tool loader) discovers SearchKnowledgeTool.

    This is the exact primitive ``Agent.get_tool`` invokes at agent.py:1234 to resolve
    the flat ``tools/search_knowledge.py`` name — proving the P4 tool is the one that
    wins the lookup (shadowing the deleted duplicate under tools/qdrant/).
    """
    assert _P4_TOOL_PATH.exists(), "tools/search_knowledge.py (P4 successor) must exist"
    classes = load_classes_from_file(str(_P4_TOOL_PATH), Tool)
    names = [c.__name__ for c in classes]
    assert "SearchKnowledgeTool" in names, f"expected SearchKnowledgeTool, found {names}"
    for c in classes:
        assert issubclass(c, Tool)


def test_p4_search_knowledge_has_execute_surface():
    """The P4 tool carries the live async ``execute`` surface (its public entry point)."""
    from tools.search_knowledge import SearchKnowledgeTool

    assert hasattr(SearchKnowledgeTool, "execute"), "P4 SearchKnowledgeTool must expose execute()"
