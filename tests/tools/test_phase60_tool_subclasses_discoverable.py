"""Phase 60.1 G2-G5: assert all 4 Phase 60 tools are Tool subclasses discoverable
by agent.get_tool() (which calls extract_tools.load_classes_from_file under the hood).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# All 4 tools require VM100_INTERNAL_BASE_URL at instantiation (Directive #4).
# For discoverability tests, set a dummy URL so __init__ doesn't fail-fast.
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")

_VM107_ROOT = Path(__file__).resolve().parents[2]
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.extract_tools import load_classes_from_file
from helpers.tool import Tool

# Each row: (module_name_seen_by_agent_get_tool, expected_wrapper_class_name)
PHASE60_TOOLS = [
    ("persist_narrative", "PersistNarrative"),
    ("get_behavioral_edges", "GetBehavioralEdges"),
    ("get_cross_trade_behavioral_patterns", "GetCrossTradeBehavioralPatterns"),
    ("get_weekly_execution_summary", "GetWeeklyExecutionSummary"),
]


@pytest.mark.parametrize("tool_module,expected_class", PHASE60_TOOLS)
def test_tool_subclass_in_module(tool_module, expected_class):
    """agent.get_tool('<tool_module>') must find a Tool subclass in tools/<tool_module>.py."""
    # Resolve repo path: VM107/tools/<tool_module>.py
    repo_root = Path(__file__).resolve().parents[2]
    tool_path = repo_root / "tools" / f"{tool_module}.py"
    assert tool_path.exists(), f"tools/{tool_module}.py does not exist"

    classes = load_classes_from_file(str(tool_path), Tool)
    assert len(classes) >= 1, f"No Tool subclass found in tools/{tool_module}.py"

    names = [c.__name__ for c in classes]
    assert expected_class in names, (
        f"Tool subclass {expected_class!r} not found in tools/{tool_module}.py — "
        f"found classes: {names}"
    )

    # All matches must actually be Tool subclasses
    for c in classes:
        assert issubclass(c, Tool), f"{c} is not a Tool subclass"


def test_persist_narrative_wrapper_instantiable():
    """PersistNarrative wrapper can be instantiated with Tool's required init args."""
    from tools.persist_narrative import PersistNarrative

    # The fake agent only needs to satisfy attribute access in Tool.__init__
    class _FakeAgent:
        pass

    wrapper = PersistNarrative(
        agent=_FakeAgent(),
        name="persist_narrative",
        method=None,
        args={},
        message="",
        loop_data=None,
    )
    assert wrapper.name == "persist_narrative"
    assert hasattr(wrapper, "execute")
