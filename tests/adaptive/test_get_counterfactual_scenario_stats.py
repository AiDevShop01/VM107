"""Phase 62-03 Task 2 — test_get_counterfactual_scenario_stats.py

Tests for get_counterfactual_scenario_stats tool:
  - Returns snapshot dict on 200 response
  - Returns None when COUNTERFACTUAL_AGGREGATE not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns None on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _try_import_get_cf_stats():
    try:
        from tools.adaptive.get_counterfactual_scenario_stats import get_counterfactual_scenario_stats
        return get_counterfactual_scenario_stats
    except ImportError as exc:
        pytest.skip(f"get_counterfactual_scenario_stats not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response returns snapshot dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cf_stats_returns_snapshot_on_200():
    """get_counterfactual_scenario_stats returns dict on 200 response."""
    get_counterfactual_scenario_stats = _try_import_get_cf_stats()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "snapshot_id": "snap-uuid",
        "cohort_snapshot_id": "cohort-uuid",
        "scenario_id": "counterfactual.stop.atr_1_5",
        "truth_mode": "ADAPTIVE_OBSERVATION",
        "n_executions": 40,
        "n_effective": 35.0,
        "avg_delta_r": 0.12,
        "is_sufficient_sample": True,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_counterfactual_scenario_stats(
            "counterfactual.stop.atr_1_5",
            "cohort-uuid",
            adaptive_signal_categories=frozenset({"COUNTERFACTUAL_AGGREGATE"}),
            http_client=mock_client,
        )

    assert result is not None
    assert result["scenario_id"] == "counterfactual.stop.atr_1_5"
    assert result["truth_mode"] == "ADAPTIVE_OBSERVATION"
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "/api/journal/internal/adaptive/counterfactual-aggregate/" in call_url


# ---------------------------------------------------------------------------
# Scope pruning: COUNTERFACTUAL_AGGREGATE not in scope → None without HTTP call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cf_stats_returns_none_when_category_not_in_scope():
    """Returns None immediately when COUNTERFACTUAL_AGGREGATE not in scope (CTX-DEC-14 / RG-10)."""
    get_counterfactual_scenario_stats = _try_import_get_cf_stats()

    mock_client = AsyncMock()

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        # Empty scope
        result_empty = await get_counterfactual_scenario_stats(
            "scenario_id", "cohort_id",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )
        # Wrong scope (STRATEGIC but not COUNTERFACTUAL_AGGREGATE)
        result_wrong = await get_counterfactual_scenario_stats(
            "scenario_id", "cohort_id",
            adaptive_signal_categories=frozenset({"STRATEGIC"}),
            http_client=mock_client,
        )

    assert result_empty is None
    assert result_wrong is None
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 → None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cf_stats_returns_none_on_404():
    """Returns None on 404 — no CF aggregate computed yet."""
    get_counterfactual_scenario_stats = _try_import_get_cf_stats()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_counterfactual_scenario_stats(
            "unknown-scenario", "unknown-cohort",
            adaptive_signal_categories=frozenset({"COUNTERFACTUAL_AGGREGATE"}),
            http_client=mock_client,
        )

    assert result is None


# ---------------------------------------------------------------------------
# Env var missing → KeyError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cf_stats_raises_keyerror_when_env_var_missing():
    """KeyError raised when VM100_INTERNAL_BASE_URL is not set."""
    get_counterfactual_scenario_stats = _try_import_get_cf_stats()

    mock_client = AsyncMock()
    env = {k: v for k, v in os.environ.items() if k != "VM100_INTERNAL_BASE_URL"}

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(KeyError):
            await get_counterfactual_scenario_stats(
                "scenario_id", "cohort_id",
                adaptive_signal_categories=frozenset({"COUNTERFACTUAL_AGGREGATE"}),
                http_client=mock_client,
            )
