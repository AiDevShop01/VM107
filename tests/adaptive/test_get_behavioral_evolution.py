"""Phase 62-04 Task 3 — test_get_behavioral_evolution.py

Tests for get_behavioral_evolution tool:
  - Returns list of rows on 200 response
  - Returns [] when BEHAVIORAL not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns [] on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
  - Accepts both enum instances and string values in adaptive_signal_categories

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _try_import_get_behavioral_evolution():
    """Return get_behavioral_evolution or skip if httpx not available."""
    try:
        from tools.adaptive.get_behavioral_evolution import (
            get_behavioral_evolution,
            _SIGNAL_CATEGORY_VALUE,
        )
        return get_behavioral_evolution, _SIGNAL_CATEGORY_VALUE
    except ImportError as exc:
        pytest.skip(f"get_behavioral_evolution not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response returns row list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_behavioral_evolution_returns_rows_on_200():
    """get_behavioral_evolution returns list of row dicts on 200 response."""
    get_behavioral_evolution, _ = _try_import_get_behavioral_evolution()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "rows": [
            {
                "series_id": "uuid-series-1",
                "account_id": "uuid-account-1",
                "cohort_snapshot_id": "uuid-cohort-1",
                "metric_family": "HESITATION",
                "metric_name": "entry_delay_seconds",
                "metric_value": 12.5,
                "trend_slope": -0.08,
                "trend_significance": 0.82,
                "effect_size": 0.42,
                "sample_size": 120,
                "required_sample_size": 100,
                "status": "SUFFICIENT",
                "truth_mode": "ADAPTIVE_OBSERVATION",
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await get_behavioral_evolution(
            "uuid-account-1",
            "uuid-cohort-1",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["metric_family"] == "HESITATION"
    assert result[0]["truth_mode"] == "ADAPTIVE_OBSERVATION"
    mock_client.get.assert_called_once()
    call_url = mock_client.get.call_args[0][0]
    assert "/api/journal/internal/adaptive/behavioral-evolution/uuid-account-1/uuid-cohort-1" in call_url


# ---------------------------------------------------------------------------
# Scope pruning: BEHAVIORAL not in scope → [] without HTTP call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_behavioral_evolution_returns_empty_when_behavioral_not_in_scope():
    """Returns [] immediately when BEHAVIORAL not in adaptive_signal_categories (CTX-DEC-14 / RG-10)."""
    get_behavioral_evolution, _ = _try_import_get_behavioral_evolution()

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        # No categories at all
        result_no_scope = await get_behavioral_evolution(
            "uuid-account-1",
            "uuid-cohort-1",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )
        # Only STRATEGIC (not BEHAVIORAL)
        result_wrong_scope = await get_behavioral_evolution(
            "uuid-account-1",
            "uuid-cohort-1",
            adaptive_signal_categories=frozenset({"STRATEGIC"}),
            http_client=mock_client,
        )
        # Only COUNTERFACTUAL_AGGREGATE (not BEHAVIORAL)
        result_cf_scope = await get_behavioral_evolution(
            "uuid-account-1",
            "uuid-cohort-1",
            adaptive_signal_categories=frozenset({"COUNTERFACTUAL_AGGREGATE"}),
            http_client=mock_client,
        )

    assert result_no_scope == []
    assert result_wrong_scope == []
    assert result_cf_scope == []
    # VM100 was NEVER called
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 → empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_behavioral_evolution_returns_empty_on_404():
    """Returns [] on 404 — no BehavioralEvolutionSeries computed yet (normal before first weekly run)."""
    get_behavioral_evolution, _ = _try_import_get_behavioral_evolution()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await get_behavioral_evolution(
            "uuid-account-1",
            "unknown-cohort-uuid",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert result == []


# ---------------------------------------------------------------------------
# Env var missing → KeyError (fail-fast discipline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_behavioral_evolution_raises_keyerror_when_env_var_missing():
    """KeyError raised when VM100_INTERNAL_BASE_URL is not set (env-driven discipline, MEMORY.md)."""
    get_behavioral_evolution, _ = _try_import_get_behavioral_evolution()

    mock_client = AsyncMock()
    env = {k: v for k, v in os.environ.items() if k != "VM100_INTERNAL_BASE_URL"}

    with pytest.MonkeyPatch().context() as mp:
        # Clear env var
        for key in list(os.environ.keys()):
            if key == "VM100_INTERNAL_BASE_URL":
                mp.delenv(key, raising=False)

        with pytest.raises(KeyError):
            await get_behavioral_evolution(
                "uuid-account-1",
                "uuid-cohort-1",
                adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
                http_client=mock_client,
            )


# ---------------------------------------------------------------------------
# Accepts enum instances in adaptive_signal_categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_behavioral_evolution_accepts_enum_instances():
    """adaptive_signal_categories may contain enum instances, not just strings."""
    get_behavioral_evolution, _ = _try_import_get_behavioral_evolution()

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

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await get_behavioral_evolution(
            "uuid-account-1",
            "uuid-cohort-1",
            adaptive_signal_categories=frozenset({AdaptiveSignalCategory.BEHAVIORAL}),
            http_client=mock_client,
        )

    assert result == []
    mock_client.get.assert_called_once()
