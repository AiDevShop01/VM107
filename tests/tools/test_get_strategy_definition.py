"""Phase 47.2-01 Wave 0 — xfail stubs for the get_strategy_definition REAL tool.

Target module: tools.get_strategy_definition
Plan 04 will graduate these xfail specs to GREEN by wrapping the Plan 03
strategy_loader (YAML → StrategyDefinition) inside a ContractTool subclass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_strategy_definition.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_loads_known_strategy(tmp_strategies_dir):
    """Loading 'model_2_option_1_short' returns a StrategyDefinition with non-empty criteria."""
    from tools.get_strategy_definition import GetStrategyDefinition  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_strategy_definition happy path"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_strategy_definition.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_unknown_strategy(tmp_strategies_dir):
    """Loading an unknown strategy returns an error Response (StrategyNotFoundError)."""
    from tools.get_strategy_definition import GetStrategyDefinition  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_strategy_definition unknown-id branch"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_strategy_definition.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_malformed_yaml(tmp_strategies_dir):
    """Loading a malformed YAML returns an error Response (MalformedStrategyError)."""
    from tools.get_strategy_definition import GetStrategyDefinition  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_strategy_definition malformed-yaml branch"
    )
