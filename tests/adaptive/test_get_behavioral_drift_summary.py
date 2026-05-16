"""Phase 62-03 Task 2 — test_get_behavioral_drift_summary.py

Tests for get_behavioral_drift_summary tool:
  - Returns BEHAVIORAL-only rows from DriftReport (non-BEHAVIORAL rows filtered out)
  - Returns [] when BEHAVIORAL not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns [] on 404 response
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


def _try_import_get_behavioral():
    try:
        from tools.adaptive.get_behavioral_drift_summary import get_behavioral_drift_summary
        return get_behavioral_drift_summary
    except ImportError as exc:
        pytest.skip(f"get_behavioral_drift_summary not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: mixed rows → only BEHAVIORAL returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_behavioral_filters_non_behavioral_rows():
    """Returns only rows with signal_category=BEHAVIORAL; non-BEHAVIORAL rows filtered out."""
    get_behavioral_drift_summary = _try_import_get_behavioral()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "rows": [
            {
                "cohort_snapshot_id": "cohort1",
                "strategy_id": "strat1",
                "scoring_category": "winrate",
                "regime_id": "regime1",
                "signal_category": "BEHAVIORAL",
                "sample_size": 40,
                "required_sample_size": 30,
                "status": "SUFFICIENT",
                "autocorrelation_deflation_method": "none",
            },
            {
                "cohort_snapshot_id": "cohort1",
                "strategy_id": "strat1",
                "scoring_category": "avg_r",
                "regime_id": "regime1",
                "signal_category": "STRATEGIC",
                "sample_size": 40,
                "required_sample_size": 30,
                "status": "SUFFICIENT",
                "autocorrelation_deflation_method": "none",
            },
            {
                "cohort_snapshot_id": "cohort1",
                "strategy_id": "strat2",
                "scoring_category": "winrate",
                "regime_id": "regime1",
                "signal_category": "BEHAVIORAL",
                "sample_size": 15,
                "required_sample_size": 30,
                "status": "INSUFFICIENT_SAMPLE",
                "autocorrelation_deflation_method": "none",
            },
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_behavioral_drift_summary(
            "cohort1",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    # Only BEHAVIORAL rows returned (2 of 3)
    assert len(result) == 2
    assert all(row["signal_category"] == "BEHAVIORAL" for row in result)
    # STRATEGIC row excluded
    assert not any(row["signal_category"] == "STRATEGIC" for row in result)


# ---------------------------------------------------------------------------
# Scope pruning: BEHAVIORAL not in scope → [] without HTTP call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_behavioral_returns_empty_when_not_in_scope():
    """Returns [] immediately when BEHAVIORAL not in adaptive_signal_categories (CTX-DEC-14 / RG-10)."""
    get_behavioral_drift_summary = _try_import_get_behavioral()

    mock_client = AsyncMock()

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result_empty = await get_behavioral_drift_summary(
            "cohort1",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )
        result_wrong = await get_behavioral_drift_summary(
            "cohort1",
            adaptive_signal_categories=frozenset({"STRATEGIC"}),
            http_client=mock_client,
        )

    assert result_empty == []
    assert result_wrong == []
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 → []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_behavioral_returns_empty_on_404():
    """Returns [] on 404 — no DriftReport yet."""
    get_behavioral_drift_summary = _try_import_get_behavioral()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_behavioral_drift_summary(
            "unknown-cohort",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert result == []


# ---------------------------------------------------------------------------
# No BEHAVIORAL rows → []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_behavioral_returns_empty_when_no_behavioral_rows_in_response():
    """Returns [] when DriftReport exists but has no BEHAVIORAL rows."""
    get_behavioral_drift_summary = _try_import_get_behavioral()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "rows": [
            {"signal_category": "STRATEGIC", "cohort_snapshot_id": "c1",
             "strategy_id": "s1", "scoring_category": "winrate",
             "regime_id": "r1", "sample_size": 30, "required_sample_size": 30,
             "status": "SUFFICIENT", "autocorrelation_deflation_method": "none"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_behavioral_drift_summary(
            "cohort1",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert result == []


# ---------------------------------------------------------------------------
# Env var missing → KeyError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_behavioral_raises_keyerror_when_env_var_missing():
    """KeyError raised when VM100_INTERNAL_BASE_URL is not set."""
    get_behavioral_drift_summary = _try_import_get_behavioral()

    mock_client = AsyncMock()
    env = {k: v for k, v in os.environ.items() if k != "VM100_INTERNAL_BASE_URL"}

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(KeyError):
            await get_behavioral_drift_summary(
                "cohort1",
                adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
                http_client=mock_client,
            )
