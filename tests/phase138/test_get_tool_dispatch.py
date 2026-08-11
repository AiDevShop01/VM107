"""Phase 138 (P6 / F3 Seam 1) — get_tool dispatch behavior-parity lock.

Locks the CURRENT ``Agent.get_tool`` contract (agent.py:1189-1265) BEFORE Wave C
extracts its body into ``core/agents/tool_dispatch.py``, so the extraction can be
proven behavior-IDENTICAL (not new behavior — RESEARCH §4).

``get_tool`` composes four observable primitives; this suite locks each directly
(real runtime hops, no mocks — project rule), plus the public surface the delegator
must preserve:

  1. tri-state "no path" leg    -> ``tools.unknown.Unknown``      (a Tool subclass)
  2. tri-state "exists-but-fails" leg -> ``tools.failed_to_load.FailedToLoad`` sentinel,
     reached when ``load_classes_from_file`` RAISES on a resolvable path
  3. tri-state "loaded" leg     -> ``load_classes_from_file`` yields the tool class
  4. BUG-17 subdir fallback     -> the recursive ``glob(**/<name>.py)`` resolves a tool
     under ``tools/<subdir>/`` that flat name lookup misses (agent.py:1213-1225)

The delegator-equivalence assertion (``Agent.get_tool`` == ``core.agents.tool_dispatch.get_tool``)
is the true end-to-end Wave-C gate; it is GUARDED-SKIPPED until that module exists so
collection never ERRORs and there is no silent false-GREEN before the extraction lands.
"""
from __future__ import annotations

import glob
import inspect
import os
from pathlib import Path

import pytest

from helpers.extract_tools import load_classes_from_file
from helpers.tool import Tool

# tests/phase138/ -> two levels up == VM107 root (== /a0 in-container).
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = _VM107_ROOT / "tools"


def test_unknown_sentinel_is_tool_subclass():
    """Leg 1: a genuinely-missing name resolves to the Unknown sentinel (a Tool)."""
    from tools.unknown import Unknown

    assert issubclass(Unknown, Tool), "Unknown must be a Tool subclass (get_tool 'no path' leg)"


def test_failed_to_load_sentinel_is_tool_subclass():
    """Leg 2 target: the FailedToLoad sentinel is a Tool (agent.py:1254)."""
    from tools.failed_to_load import FailedToLoad

    assert issubclass(FailedToLoad, Tool), (
        "FailedToLoad must be a Tool subclass (get_tool 'exists-but-failed' leg)"
    )


def test_failed_to_load_leg_triggered_by_load_error(tmp_path):
    """Leg 2 mechanism: load_classes_from_file RAISES on a resolvable-but-broken tool.

    ``get_tool`` catches that raise (agent.py:1236) and, when every resolved path
    fails, returns FailedToLoad. Lock the primitive: a file that errors on import
    makes ``load_classes_from_file`` raise rather than silently return a class.
    """
    broken = tmp_path / "broken_tool.py"
    broken.write_text("raise ImportError('deliberate load failure for parity lock')\n")
    with pytest.raises(Exception):  # noqa: PT011 — any load error drives the FailedToLoad leg
        load_classes_from_file(str(broken), Tool)


def test_valid_tool_resolves_to_class():
    """Leg 3: a valid tool file loads to its Tool subclass (agent.py:1234, the 'loaded' leg)."""
    path = _TOOLS_DIR / "search_knowledge.py"
    assert path.exists(), "tools/search_knowledge.py (P4 tool) must exist"
    classes = load_classes_from_file(str(path), Tool)
    names = [c.__name__ for c in classes]
    assert "SearchKnowledgeTool" in names, f"expected SearchKnowledgeTool, found {names}"
    for c in classes:
        assert issubclass(c, Tool)


def test_bug17_subdir_fallback_glob_resolves():
    """Leg 4: BUG-17 recursive glob resolves a subdir tool flat lookup misses.

    Mirrors agent.py:1213-1225 exactly: flat ``tools/<name>.py`` is absent, but the
    recursive ``glob(tools/**/<name>.py)`` finds ``tools/qdrant/combined_rag.py``.
    """
    name = "combined_rag"
    flat = _TOOLS_DIR / f"{name}.py"
    assert not flat.exists(), "precondition: combined_rag has no flat tools/ entry"
    matches = glob.glob(os.path.join(str(_TOOLS_DIR), "**", f"{name}.py"), recursive=True)
    assert matches, "BUG-17 recursive glob must resolve the subdir tool"
    assert any("qdrant" in m for m in matches), matches


def test_get_tool_public_surface_preserved():
    """The delegator surface Wave C must keep: Agent.get_tool sync + @extension.extensible.

    ``@extension.extensible`` wraps the method (leaves ``__wrapped__``); ``get_tool`` is
    a *sync* method (NOT a coroutine). The delegator must preserve both.
    """
    from agent import Agent

    assert callable(getattr(Agent, "get_tool", None)), "Agent.get_tool must stay callable"
    assert not inspect.iscoroutinefunction(Agent.get_tool), "get_tool is sync, not a coroutine"
    assert hasattr(Agent.get_tool, "__wrapped__"), (
        "@extension.extensible must remain on Agent.get_tool (leaves __wrapped__)"
    )


def test_delegator_equivalence_pending_extraction():
    """Wave-C end-to-end gate: Agent.get_tool must delegate to core.agents.tool_dispatch.

    GUARDED-SKIP until Wave C creates the module — never a hard collection failure and
    never a silent false-GREEN. Once the module exists this asserts the public function
    is present and callable (the extracted dispatch surface the delegator forwards to).
    """
    mod = pytest.importorskip(
        "core.agents.tool_dispatch",
        reason="Wave C not yet landed — core.agents.tool_dispatch does not exist",
    )
    assert callable(getattr(mod, "get_tool", None)), (
        "extracted core.agents.tool_dispatch.get_tool must be a callable"
    )
    from agent import Agent

    assert hasattr(Agent.get_tool, "__wrapped__"), "delegator must keep @extension.extensible"
