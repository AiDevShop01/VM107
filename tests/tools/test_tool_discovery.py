"""Phase 47.2-01 Wave 0 — xfail tool/prompt discovery checks.

Target modules: tools/<name>.py + prompts/agent.system.tool.<name>.md
Plans 04+05 will graduate these xfail specs to GREEN once all 9 tool files
and 9 prompt descriptors are present on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent

_TOOL_NAMES = [
    "get_trade_context",
    "get_primitives",
    "get_liquidity_context",
    "get_strategy_definition",
    "get_macro_context",
    "get_news_context",
    "get_regime_context",
    "get_sentiment_context",
    "get_performance_history",
]


@pytest.mark.xfail(
    reason="Wave 0 stub — Plans 04+05 ship the 9 tool files",
    strict=False,
)
def test_all_9_tools_discoverable():
    """All 9 tool files must exist under VM107/tools/."""
    missing = [
        name for name in _TOOL_NAMES if not (_VM107_ROOT / "tools" / f"{name}.py").exists()
    ]
    if missing:
        pytest.fail(f"Wave 0 stub — Plans 04+05 implement: {missing}")


@pytest.mark.xfail(
    reason="Wave 0 stub — Plans 04+05 ship the 9 prompt descriptors",
    strict=False,
)
def test_all_9_prompts_present():
    """All 9 prompt descriptor files must exist under VM107/prompts/."""
    missing = [
        name
        for name in _TOOL_NAMES
        if not (_VM107_ROOT / "prompts" / f"agent.system.tool.{name}.md").exists()
    ]
    if missing:
        pytest.fail(f"Wave 0 stub — Plans 04+05 implement prompts for: {missing}")
