"""Phase 62-06 Task 3 — test_get_regime_adaptation_candidates.py

Tests for get_regime_adaptation_candidates tool:
  - Returns list of candidate rows on 200 response
  - Raises ToolError if _shadow_only=False or missing (envelope enforcement)
  - Returns [] when REGIME_ADAPTATION not in adaptive_signal_categories (CTX-DEC-14)
  - Returns [] on 404 response
  - Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing (env-driven discipline)
  - scope gating: REGIME_ADAPTATION category required

CTX-DEC-14: Scope-gated tool — returns [] immediately if category not in scope.
CTX-DEC-15: Shadow-only enforcement — ToolError if _shadow_only flag missing/False.
RG-11: Envelope flag is a load-bearing defense-in-depth layer at tool level.

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
    """Return get_regime_adaptation_candidates or skip if httpx not available."""
    try:
        from tools.adaptive.get_regime_adaptation_candidates import (
            get_regime_adaptation_candidates,
            _SIGNAL_CATEGORY_VALUE,
            ToolError,
        )
        return get_regime_adaptation_candidates, _SIGNAL_CATEGORY_VALUE, ToolError
    except ImportError as exc:
        pytest.skip(f"get_regime_adaptation_candidates not importable: {exc}")


# ---------------------------------------------------------------------------
# Happy-path: 200 response with _shadow_only=True returns candidate rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_regime_candidates_returns_rows_on_200_with_shadow_only():
    """get_regime_adaptation_candidates returns rows when _shadow_only=True in response."""
    func, _, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "_shadow_only": True,  # MANDATORY flag
        "cohort_snapshot_id": "test-cohort-uuid",
        "rows": [
            {
                "candidate_id": "cand-uuid-001",
                "regime_id": "regime-abc",
                "target_cohort_key": "strategy=x|category=y|regime=abc",
                "recommended_threshold": 0.72,
                "status": "SHADOW_ONLY",
                "origin_mode": "LIVE_FORWARD_ACCUMULATION",
            }
        ],
        "count": 1,
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "httpx.AsyncClient", return_value=mock_client
    ):
        os.environ["VM100_INTERNAL_BASE_URL"] = "http://test-vm100"
        result = await func(
            cohort_snapshot_id="test-cohort-uuid",
            adaptive_signal_categories=frozenset(["REGIME_ADAPTATION"]),
        )
        del os.environ["VM100_INTERNAL_BASE_URL"]

    assert len(result) == 1
    assert result[0]["candidate_id"] == "cand-uuid-001"


# ---------------------------------------------------------------------------
# RG-11: ToolError raised when _shadow_only missing or False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_tool_error_when_shadow_only_missing():
    """ToolError raised when _shadow_only is missing from response envelope.

    RG-11 + CTX-DEC-15: The tool MUST refuse to surface candidates if the
    envelope flag is absent. Defense-in-depth at tool layer.
    """
    func, _, ToolError = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        # _shadow_only flag is ABSENT — this must raise ToolError
        "rows": [{"candidate_id": "cand-001"}],
        "count": 1,
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "httpx.AsyncClient", return_value=mock_client
    ):
        os.environ["VM100_INTERNAL_BASE_URL"] = "http://test-vm100"
        with pytest.raises(ToolError, match="SHADOW_ONLY"):
            await func(
                cohort_snapshot_id="test-cohort-uuid",
                adaptive_signal_categories=frozenset(["REGIME_ADAPTATION"]),
            )
        del os.environ["VM100_INTERNAL_BASE_URL"]


@pytest.mark.asyncio
async def test_raises_tool_error_when_shadow_only_is_false():
    """ToolError raised when _shadow_only=False in response envelope.

    RG-11: Even if the flag exists but is False, tool must raise.
    """
    func, _, ToolError = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "_shadow_only": False,  # False is also forbidden
        "rows": [{"candidate_id": "cand-001"}],
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "httpx.AsyncClient", return_value=mock_client
    ):
        os.environ["VM100_INTERNAL_BASE_URL"] = "http://test-vm100"
        with pytest.raises(ToolError, match="SHADOW_ONLY"):
            await func(
                cohort_snapshot_id="test-cohort-uuid",
                adaptive_signal_categories=frozenset(["REGIME_ADAPTATION"]),
            )
        del os.environ["VM100_INTERNAL_BASE_URL"]


# ---------------------------------------------------------------------------
# CTX-DEC-14: Scope gating — returns [] if REGIME_ADAPTATION not in scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_gating_returns_empty_when_category_absent():
    """Returns [] when REGIME_ADAPTATION not in adaptive_signal_categories (CTX-DEC-14)."""
    func, _, _ = _try_import()

    result = await func(
        cohort_snapshot_id="test-cohort-uuid",
        adaptive_signal_categories=frozenset(["BEHAVIORAL"]),  # REGIME_ADAPTATION absent
    )
    assert result == []


@pytest.mark.asyncio
async def test_scope_gating_returns_empty_for_empty_categories():
    """Returns [] when adaptive_signal_categories is empty."""
    func, _, _ = _try_import()

    result = await func(
        cohort_snapshot_id="test-cohort-uuid",
        adaptive_signal_categories=frozenset(),
    )
    assert result == []


# ---------------------------------------------------------------------------
# 404 response → returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_on_404():
    """Returns [] on 404 response (cohort has no regime adaptation candidates yet)."""
    func, _, _ = _try_import()

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"_shadow_only": True, "error": "not found"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "httpx.AsyncClient", return_value=mock_client
    ):
        os.environ["VM100_INTERNAL_BASE_URL"] = "http://test-vm100"
        result = await func(
            cohort_snapshot_id="test-cohort-uuid",
            adaptive_signal_categories=frozenset(["REGIME_ADAPTATION"]),
        )
        del os.environ["VM100_INTERNAL_BASE_URL"]

    assert result == []


# ---------------------------------------------------------------------------
# Env-driven: raises KeyError when VM100_INTERNAL_BASE_URL missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_key_error_when_env_var_missing():
    """Raises KeyError when VM100_INTERNAL_BASE_URL env var is missing.

    MEMORY.md env-driven-no-fallbacks discipline: fail-fast beats silent misconfiguration.
    """
    func, _, _ = _try_import()

    # Remove env var
    os.environ.pop("VM100_INTERNAL_BASE_URL", None)

    with pytest.raises(KeyError):
        await func(
            cohort_snapshot_id="test-cohort-uuid",
            adaptive_signal_categories=frozenset(["REGIME_ADAPTATION"]),
        )
