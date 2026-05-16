"""Phase 62-05 Task 3 — test_get_pattern_cluster_stats.py

Tests for get_pattern_cluster_stats tool:
  - Returns dict on 200 response
  - Returns None when PATTERN not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns None on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
  - Accepts both enum instances and string values in adaptive_signal_categories

CTX-DEC-13: PATTERN scope. Cluster stats reflect structured vector clustering only.
Pitfall 7: cluster labels are deterministic centroid-hash descriptors.

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


def _try_import():
    """Return get_pattern_cluster_stats or skip if httpx not available."""
    try:
        from tools.adaptive.get_pattern_cluster_stats import (
            get_pattern_cluster_stats,
            _SIGNAL_CATEGORY_VALUE,
        )
        return get_pattern_cluster_stats, _SIGNAL_CATEGORY_VALUE
    except ImportError as exc:
        pytest.skip(f"get_pattern_cluster_stats not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response returns stats dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stats_returns_dict_on_200():
    """Returns dict with cluster stats on 200 response."""
    func, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "cluster_snapshot_id": "snap-uuid-789",
        "cohort_snapshot_id": "cohort-uuid-123",
        "clustering_method": "hdbscan_v1",
        "cluster_count": 3,
        "noise_count": 5,
        "total_executions": 60,
        "cluster_labels": {
            "c0": "cluster_0_centroid_abc123def456",
            "c1": "cluster_1_centroid_789ghi012jkl",
        },
        "status": "SUFFICIENT",
        "truth_mode": "ADAPTIVE_OBSERVATION",
        "required_sample_size": 50,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "snap-uuid-789",
            adaptive_signal_categories=frozenset({"PATTERN"}),
            http_client=mock_client,
        )

    assert isinstance(result, dict)
    assert result["clustering_method"] == "hdbscan_v1"
    assert result["truth_mode"] == "ADAPTIVE_OBSERVATION"
    assert result["status"] == "SUFFICIENT"
    assert "cluster_labels" in result


# ---------------------------------------------------------------------------
# Scope pruning: PATTERN not in categories → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_none_when_pattern_not_in_scope():
    """Returns None when PATTERN is not in adaptive_signal_categories (CTX-DEC-14)."""
    func, cat_value = _try_import()
    assert cat_value == "PATTERN"

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "snap-uuid-789",
            adaptive_signal_categories=frozenset({"BEHAVIORAL"}),
            http_client=mock_client,
        )

    assert result is None
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_when_empty_scope():
    """Returns None when adaptive_signal_categories is empty."""
    func, _ = _try_import()

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "snap-uuid-789",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )

    assert result is None
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 response → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_none_on_404():
    """Returns None on 404 (cluster snapshot not found)."""
    func, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "snap-uuid-nonexistent",
            adaptive_signal_categories=frozenset({"PATTERN"}),
            http_client=mock_client,
        )

    assert result is None


# ---------------------------------------------------------------------------
# Missing env var → KeyError (env-driven config discipline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_key_error_when_env_var_missing():
    """Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (fail-fast)."""
    func, _ = _try_import()

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.delenv("VM100_INTERNAL_BASE_URL", raising=False)
        with pytest.raises(KeyError):
            await func(
                "snap-uuid-789",
                adaptive_signal_categories=frozenset({"PATTERN"}),
                http_client=mock_client,
            )


# ---------------------------------------------------------------------------
# Accepts enum instances as well as string values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepts_enum_values_in_scope():
    """Accepts enum instances (with .value attribute) in adaptive_signal_categories."""
    func, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "cluster_snapshot_id": "snap-uuid-999",
        "status": "SUFFICIENT",
        "truth_mode": "ADAPTIVE_OBSERVATION",
        "clustering_method": "hdbscan_v1",
        "cluster_count": 2,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    class MockPatternEnum:
        value = "PATTERN"

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "snap-uuid-999",
            adaptive_signal_categories=frozenset({MockPatternEnum()}),
            http_client=mock_client,
        )

    assert result is not None
    assert isinstance(result, dict)
