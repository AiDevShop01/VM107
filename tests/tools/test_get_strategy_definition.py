"""Phase 47.2-04 — graduated GREEN tests for the get_strategy_definition REAL tool.

Target module: tools.get_strategy_definition
Wave 0 stubs graduated per Plan 04: happy path, unknown strategy, malformed YAML.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _make_tool(strategy_id: str):
    from tools.get_strategy_definition import GetStrategyDefinition

    return GetStrategyDefinition(
        agent=MagicMock(),
        name="get_strategy_definition",
        method=None,
        args={"strategy_id": strategy_id},
        message="",
        loop_data=None,
    )


@pytest.mark.asyncio
async def test_loads_known_strategy():
    """Loading 'model_2_option_1_short' returns a serialised StrategyDefinition."""
    tool = _make_tool("model_2_option_1_short")
    response = await tool.execute(strategy_id="model_2_option_1_short")

    assert response.break_loop is False
    payload = json.loads(response.message)
    assert payload["id"] == "model_2_option_1_short"
    assert payload["version"] == 1
    assert isinstance(payload["criteria"], list) and payload["criteria"]
    assert isinstance(payload["hard_rejects"], list) and payload["hard_rejects"]


@pytest.mark.asyncio
async def test_unknown_strategy():
    """Unknown strategy_id surfaces a non-fatal error Response (StrategyNotFoundError)."""
    from core.agents.strategy_loader import StrategyNotFoundError

    tool = _make_tool("does_not_exist_strategy")
    with patch(
        "tools.get_strategy_definition.load_strategy",
        side_effect=StrategyNotFoundError("missing"),
    ):
        response = await tool.execute(strategy_id="does_not_exist_strategy")

    assert response.break_loop is False
    assert "missing" in response.message or "not found" in response.message.lower()


@pytest.mark.asyncio
async def test_malformed_yaml():
    """Malformed YAML surfaces a non-fatal error Response (MalformedStrategyError)."""
    from core.agents.strategy_loader import MalformedStrategyError

    tool = _make_tool("broken_strategy")
    with patch(
        "tools.get_strategy_definition.load_strategy",
        side_effect=MalformedStrategyError("schema validation failed"),
    ):
        response = await tool.execute(strategy_id="broken_strategy")

    assert response.break_loop is False
    assert "schema validation failed" in response.message
