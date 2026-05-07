"""Phase 47.2-01 Wave 0 — xfail stubs for the strategy YAML loader.

Target module: core.agents.strategy_loader
Plan 03 will graduate these xfail specs to GREEN by shipping the
load_strategy(strategy_id) helper that:
  - reads agents/agent0/strategies/<id>.yaml fresh on every call
  - validates the YAML against the StrategyDefinition Pydantic schema (Plan 02)
  - raises StrategyNotFoundError when the file is missing
  - raises MalformedStrategyError when YAML is invalid or schema-violating
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 03 implements core/agents/strategy_loader.py",
    strict=False,
)
def test_load_strategy_returns_dict(tmp_path):
    """load_strategy(valid_id) returns a dict with id/version/criteria/hard_rejects."""
    from core.agents.strategy_loader import load_strategy  # noqa: F401

    pytest.fail("Wave 0 stub — Plan 03 implements strategy_loader.load_strategy happy path")


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 03 implements core/agents/strategy_loader.py",
    strict=False,
)
def test_missing_file_raises(tmp_path):
    """load_strategy(unknown_id) raises StrategyNotFoundError."""
    from core.agents.strategy_loader import (  # noqa: F401
        StrategyNotFoundError,
        load_strategy,
    )

    pytest.fail("Wave 0 stub — Plan 03 implements strategy_loader StrategyNotFoundError")


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 03 implements core/agents/strategy_loader.py",
    strict=False,
)
def test_malformed_yaml_raises(tmp_path):
    """load_strategy(bad_yaml_id) raises MalformedStrategyError."""
    from core.agents.strategy_loader import (  # noqa: F401
        MalformedStrategyError,
        load_strategy,
    )

    pytest.fail("Wave 0 stub — Plan 03 implements strategy_loader MalformedStrategyError")
