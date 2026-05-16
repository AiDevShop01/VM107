"""Phase 62-03 Task 2 — test_get_drift_report.py

Tests for get_drift_report tool:
  - Returns list of rows on 200 response
  - Returns [] when STRATEGIC not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns [] on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
  - Accepts both enum instances and string values in adaptive_signal_categories
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


def _try_import_get_drift_report():
    """Return get_drift_report or skip if httpx not available."""
    try:
        from tools.adaptive.get_drift_report import get_drift_report, _SIGNAL_CATEGORY_VALUE
        return get_drift_report, _SIGNAL_CATEGORY_VALUE
    except ImportError as exc:
        pytest.skip(f"get_drift_report not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response returns row list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_returns_rows_on_200():
    """get_drift_report returns list of row dicts on 200 response."""
    get_drift_report, _ = _try_import_get_drift_report()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "rows": [
            {"cohort_snapshot_id": "abc123", "strategy_id": "strat1",
             "scoring_category": "winrate", "regime_id": "regime1",
             "sample_size": 35, "required_sample_size": 30,
             "status": "SUFFICIENT", "drift_score": 0.15,
             "autocorrelation_deflation_method": "none"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_drift_report(
            "test-cohort-uuid",
            adaptive_signal_categories=frozenset({"STRATEGIC"}),
            http_client=mock_client,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["strategy_id"] == "strat1"
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "/api/journal/internal/adaptive/drift-report/test-cohort-uuid" in call_url


# ---------------------------------------------------------------------------
# Scope pruning: STRATEGIC not in scope → [] without HTTP call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_returns_empty_when_strategic_not_in_scope():
    """Returns [] immediately when STRATEGIC not in adaptive_signal_categories (CTX-DEC-14 / RG-10)."""
    get_drift_report, _ = _try_import_get_drift_report()

    mock_client = AsyncMock()

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        # No categories at all
        result_no_scope = await get_drift_report(
            "test-cohort-uuid",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )
        # Only BEHAVIORAL (not STRATEGIC)
        result_wrong_scope = await get_drift_report(
            "test-cohort-uuid",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert result_no_scope == []
    assert result_wrong_scope == []
    # VM100 was NEVER called
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 → empty list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_returns_empty_on_404():
    """Returns [] on 404 — no DriftReport computed yet (normal before first weekly run)."""
    get_drift_report, _ = _try_import_get_drift_report()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_drift_report(
            "unknown-cohort-uuid",
            adaptive_signal_categories=frozenset({"STRATEGIC"}),
            http_client=mock_client,
        )

    assert result == []


# ---------------------------------------------------------------------------
# Env var missing → KeyError (fail-fast discipline)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_raises_keyerror_when_env_var_missing():
    """KeyError raised when VM100_INTERNAL_BASE_URL is not set (env-driven discipline, MEMORY.md)."""
    get_drift_report, _ = _try_import_get_drift_report()

    mock_client = AsyncMock()
    env = {k: v for k, v in os.environ.items() if k != "VM100_INTERNAL_BASE_URL"}

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(KeyError):
            await get_drift_report(
                "test-cohort-uuid",
                adaptive_signal_categories=frozenset({"STRATEGIC"}),
                http_client=mock_client,
            )


# ---------------------------------------------------------------------------
# Accepts enum instances in adaptive_signal_categories
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_drift_report_accepts_enum_instances():
    """adaptive_signal_categories may contain enum instances, not just strings."""
    get_drift_report, _ = _try_import_get_drift_report()

    try:
        from fingpt_core.contracts.adaptive.enums import AdaptiveSignalCategory
    except ImportError:
        pytest.skip("fingpt_core not available")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"rows": []}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.dict(os.environ, {"VM100_INTERNAL_BASE_URL": "http://vm100-internal:8000"}):
        result = await get_drift_report(
            "test-cohort-uuid",
            adaptive_signal_categories=frozenset({AdaptiveSignalCategory.STRATEGIC}),
            http_client=mock_client,
        )

    assert result == []
    mock_client.get.assert_called_once()
