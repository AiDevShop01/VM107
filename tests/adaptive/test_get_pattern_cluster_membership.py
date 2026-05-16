"""Phase 62-05 Task 3 — test_get_pattern_cluster_membership.py

Tests for get_pattern_cluster_membership tool:
  - Returns list with row dict on 200 response
  - Returns [] when PATTERN not in adaptive_signal_categories (CTX-DEC-14 / RG-10)
  - Returns [] on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
  - Accepts both enum instances and string values in adaptive_signal_categories

CTX-DEC-13: PATTERN scope. Cluster membership reflects structured vector clustering only.
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
    """Return get_pattern_cluster_membership or skip if httpx not available."""
    try:
        from tools.adaptive.get_pattern_cluster_membership import (
            get_pattern_cluster_membership,
            _SIGNAL_CATEGORY_VALUE,
        )
        return get_pattern_cluster_membership, _SIGNAL_CATEGORY_VALUE
    except ImportError as exc:
        pytest.skip(f"get_pattern_cluster_membership not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response returns membership row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_membership_returns_row_on_200():
    """Returns list with membership dict on 200 response."""
    func, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "execution_id": "exec-uuid-123",
        "cluster_id": "c1",
        "cluster_label": "cluster_1_centroid_abc123def456",
        "cluster_snapshot_id": "snap-uuid-456",
        "generated_at": "2026-01-01T23:00:00Z",
        "truth_mode": "ADAPTIVE_OBSERVATION",
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "exec-uuid-123",
            adaptive_signal_categories=frozenset({"PATTERN"}),
            http_client=mock_client,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["cluster_id"] == "c1"
    assert result[0]["truth_mode"] == "ADAPTIVE_OBSERVATION"


# ---------------------------------------------------------------------------
# Scope pruning: PATTERN not in categories → []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_when_pattern_not_in_scope():
    """Returns [] when PATTERN is not in adaptive_signal_categories (CTX-DEC-14)."""
    func, cat_value = _try_import()
    assert cat_value == "PATTERN"

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "exec-uuid-123",
            adaptive_signal_categories=frozenset({"BEHAVIORAL", "STRATEGIC"}),
            http_client=mock_client,
        )

    assert result == [], (
        "get_pattern_cluster_membership must return [] when PATTERN not in categories"
    )
    # Must NOT call VM100
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_returns_empty_when_empty_scope():
    """Returns [] when adaptive_signal_categories is empty."""
    func, _ = _try_import()

    mock_client = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "exec-uuid-123",
            adaptive_signal_categories=frozenset(),
            http_client=mock_client,
        )

    assert result == []
    mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 404 response → []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_on_404():
    """Returns [] on 404 (no cluster membership for execution)."""
    func, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "exec-uuid-nonexistent",
            adaptive_signal_categories=frozenset({"PATTERN"}),
            http_client=mock_client,
        )

    assert result == []


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
                "exec-uuid-123",
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
        "cluster_id": "c0",
        "cluster_label": "cluster_0_centroid_xyz789",
        "cluster_snapshot_id": "snap-1",
        "generated_at": "2026-02-01T23:00:00Z",
        "truth_mode": "ADAPTIVE_OBSERVATION",
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    # Create mock enum with .value attribute
    class MockPatternEnum:
        value = "PATTERN"

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("VM100_INTERNAL_BASE_URL", "http://vm100-internal:8000")
        result = await func(
            "exec-uuid-123",
            adaptive_signal_categories=frozenset({MockPatternEnum()}),
            http_client=mock_client,
        )

    assert isinstance(result, list)
    assert len(result) == 1
