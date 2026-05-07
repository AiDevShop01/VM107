"""Phase 47.2-05 — graduated GREEN tests for tool/prompt discovery.

Target: all 9 Wave 3 tools must have one-file-per-tool at VM107/tools/<name>.py
and a sibling prompt descriptor at VM107/prompts/agent.system.tool.<name>.md.

Plans 04+05 ship the 9 tools and prompts; this spec turns GREEN once both
plans land (Plan 04 = 4 real tools, Plan 05 = 5 stub tools).
"""
from __future__ import annotations

from pathlib import Path

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


def test_all_9_tools_discoverable():
    """All 9 tool files must exist under VM107/tools/."""
    missing = [
        name for name in _TOOL_NAMES if not (_VM107_ROOT / "tools" / f"{name}.py").exists()
    ]
    assert missing == [], f"Missing tool files: {missing}"


def test_all_9_prompts_present():
    """All 9 prompt descriptor files must exist under VM107/prompts/."""
    missing = [
        name
        for name in _TOOL_NAMES
        if not (_VM107_ROOT / "prompts" / f"agent.system.tool.{name}.md").exists()
    ]
    assert missing == [], f"Missing prompt descriptors: {missing}"
