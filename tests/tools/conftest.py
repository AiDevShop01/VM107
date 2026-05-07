"""Phase 47.2-01 Wave 0 — shared fixtures for the VM107 tests/tools/ suite.

Plans 02–07 will graduate the xfail stubs in this directory to GREEN by
shipping the typed contracts, real tools, stub tools, strategy loader, and
Tier-1 context builder. These fixtures are intentionally light — they exist
purely so the xfail specs collect cleanly.

Provided fixtures:
- mock_vm100_client       — AsyncMock returning a canned trade dict
- mock_polars_scan        — patches polars.scan_parquet with a fake DataFrame
- tmp_strategies_dir      — creates tmp_path/strategies/model_2_option_1_short.yaml
- mock_agent              — MagicMock for an Agent instance with get_tool/agent_id
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


_CANNED_TRADE = {
    "trade_id": "abc123",
    "instrument": "EURUSD",
    "direction": "short",
    "strategy_id": "model_2_option_1_short",
    "entry_price": 1.0950,
    "stop_loss_price": 1.0975,
    "take_profit_price": 1.0900,
    "timeframe": "M5",
    "notes": "Compression at HTF resistance.",
}


@pytest.fixture
def mock_vm100_client():
    """AsyncMock VM100Client returning a canned trade payload."""
    client = MagicMock()
    client.get_trade = AsyncMock(return_value=dict(_CANNED_TRADE))
    return client


@pytest.fixture
def mock_polars_scan(monkeypatch):
    """Patch polars.scan_parquet with a fake DataFrame stand-in.

    Plans 04+ will install proper assertions against the captured calls.
    Wave 0 only needs the symbol present so xfail specs can import.
    """
    fake_df = MagicMock(name="fake_polars_df")
    fake_df.collect.return_value = MagicMock(name="fake_collected_df")
    scan = MagicMock(return_value=fake_df)
    try:
        import polars as pl  # noqa: F401
        monkeypatch.setattr("polars.scan_parquet", scan, raising=False)
    except ImportError:
        # Wave 0 stubs do not actually exercise polars; tolerate absence.
        pass
    return scan


@pytest.fixture
def tmp_strategies_dir(tmp_path):
    """Create tmp_path/strategies/model_2_option_1_short.yaml with valid content.

    Plan 03 strategy_loader tests will read from this directory.
    """
    strategies = tmp_path / "strategies"
    strategies.mkdir(parents=True, exist_ok=True)
    yaml_path = strategies / "model_2_option_1_short.yaml"
    yaml_path.write_text(
        """\
id: model_2_option_1_short
version: 1
description: Momentum continuation short strategy
criteria:
  - name: HTF trend alignment
    required: true
  - name: compression present
    required: true
  - name: breakout with displacement
    required: true
  - name: continuation structure
    required: true
  - name: liquidity sweep
    required: preferred
hard_rejects:
  - name: breakout into HVN
  - name: no displacement
  - name: against HTF trend
scoring:
  max_score: 7
"""
    )
    return strategies


@pytest.fixture
def mock_agent():
    """MagicMock for an Agent instance — exposes agent_id and get_tool."""
    agent = MagicMock()
    agent.agent_id = "agent_zero"
    agent.get_tool = MagicMock()
    return agent
