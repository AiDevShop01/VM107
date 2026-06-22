"""Phase 89.1 Option-B — unit tests for 7 vm102 indicator proxy tools.

Strategy: mock VM102Client.get() at the class level — no live VM102 calls.
Tests cover:
  1. Happy path — correct payload shape and field mapping
  2. HTTP error paths — 401, 404, timeout → FailureModeCode mapping
  3. Domain errors — empty response, EventStudySampleTooSmall, bad window value
  4. No fallback defaults — VM102_API_URL unset raises RuntimeError

Proxies under test:
  - vm102_indicator_history
  - vm102_indicator_regime
  - vm102_indicator_releases
  - vm102_indicator_distribution
  - vm102_indicator_asset_exposure
  - vm102_indicator_event_study
  - vm102_indicator_correlations
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure VM107 root on path for imports
import pathlib
VM107_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(VM107_ROOT))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def set_vm102_url(monkeypatch):
    """Patch VM102_API_URL into environment for proxy constructors."""
    monkeypatch.setenv("VM102_API_URL", "http://vm102-test:8003")


@pytest.fixture
def mock_vm102_client():
    """Return a context manager that patches VM102Client.get to return a fixed dict."""
    def _make(return_value: dict):
        mock = AsyncMock(return_value=return_value)
        return patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=mock,
        ), mock
    return _make


# ---------------------------------------------------------------------------
# Helper to assert ToolProvenance is populated
# ---------------------------------------------------------------------------

def _has_provenance(payload) -> bool:
    return hasattr(payload, "provenance") and payload.provenance is not None


# =========================================================================
# vm102_indicator_history
# =========================================================================

class TestVm102IndicatorHistory:

    def test_happy_path_maps_fields(self, set_vm102_url):
        """Valid response → payload fields populated correctly."""
        from tools.proxies import vm102_indicator_history as proxy

        fake_response = {
            "indicator_id": "CPIAUCSL",
            "range": "5Y",
            "series": [{"ts": "2026-01-10T00:00:00Z", "value": 3.4}],
            "overlays": {
                "recessions": [{"start": "2020-01-01", "end": "2020-04-30", "label": "COVID"}],
                "rate_hikes": [],
                "qe_periods": [],
            },
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 3600,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", range="5Y")
            )

        assert result.indicator_id == "CPIAUCSL"
        assert result.range == "5Y"
        assert len(result.series) == 1
        assert result.series[0]["value"] == 3.4
        assert len(result.overlays.recessions) == 1
        assert result.ttl_seconds == 3600
        assert _has_provenance(result)

    def test_404_returns_no_match_found(self, set_vm102_url):
        """HTTP 404 → FailureModeCode.NO_MATCH_FOUND, empty series."""
        from tools.proxies import vm102_indicator_history as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("HTTP 404 not found")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="BOGUS")
            )

        assert result.indicator_id == "BOGUS"
        assert result.series == []
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.NO_MATCH_FOUND in fm_codes

    def test_invalid_range_returns_validation_failed(self, set_vm102_url):
        """Invalid range string → VALIDATION_FAILED without calling VM102."""
        from tools.proxies import vm102_indicator_history as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            proxy.run_async(indicator_id="CPIAUCSL", range="BOGUS")
        )

        assert result.series == []
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.VALIDATION_FAILED in fm_codes

    def test_timeout_returns_upstream_timeout(self, set_vm102_url):
        """Connection error → FailureModeCode.UPSTREAM_TIMEOUT."""
        from tools.proxies import vm102_indicator_history as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("Connection timeout")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.UPSTREAM_TIMEOUT in fm_codes


# =========================================================================
# vm102_indicator_regime
# =========================================================================

class TestVm102IndicatorRegime:

    def test_happy_path_maps_fields(self, set_vm102_url):
        from tools.proxies import vm102_indicator_regime as proxy

        fake_response = {
            "indicator_id": "CPIAUCSL",
            "current_value": 3.4,
            "current_regime": {
                "label": "ELEVATED",
                "bucket_index": 2,
                "bucket_lower": 2.5,
                "bucket_upper": 5.0,
            },
            "regime_history": [
                {"ts": "2026-05-12T00:00:00Z", "regime_label": "ELEVATED"},
            ],
            "thresholds": [
                {"max": 2.5, "label": "TARGET"},
                {"max": None, "label": "ELEVATED"},
            ],
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 300,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        assert result.indicator_id == "CPIAUCSL"
        assert result.current_value == 3.4
        assert result.current_regime["label"] == "ELEVATED"
        assert len(result.regime_history) == 1
        assert len(result.thresholds) == 2
        assert result.ttl_seconds == 300
        assert _has_provenance(result)

    def test_404_returns_no_match_found(self, set_vm102_url):
        from tools.proxies import vm102_indicator_regime as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("404 not found")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="BOGUS")
            )

        assert result.current_regime is None
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.NO_MATCH_FOUND in fm_codes

    def test_auth_error_returns_permission_denied(self, set_vm102_url):
        from tools.proxies import vm102_indicator_regime as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("401 Unauthorized")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.PERMISSION_DENIED in fm_codes


# =========================================================================
# vm102_indicator_releases
# =========================================================================

class TestVm102IndicatorReleases:

    def test_happy_path_maps_releases(self, set_vm102_url):
        from tools.proxies import vm102_indicator_releases as proxy

        fake_response = {
            "indicator_id": "CPIAUCSL",
            "releases": [
                {
                    "event_id": "42",
                    "release_ts": "2026-06-12T12:30:00Z",
                    "previous": 3.2,
                    "forecast": 3.3,
                    "actual": 3.4,
                    "surprise": 0.1,
                    "surprise_pct": 3.03,
                }
            ],
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 60,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", limit=12)
            )

        assert result.indicator_id == "CPIAUCSL"
        assert len(result.releases) == 1
        assert result.releases[0]["actual"] == 3.4
        assert result.releases[0]["surprise"] == 0.1
        assert result.ttl_seconds == 60
        assert _has_provenance(result)

    def test_limit_clamped_to_max(self, set_vm102_url):
        """Limit > 60 is clamped to 60 before the request."""
        from tools.proxies import vm102_indicator_releases as proxy

        captured_params: dict = {}

        async def _capture_get(self_or_path, path_or_params=None, params=None, **kwargs):
            # Called as bound method mock — first arg is self, second is path, params is kwarg
            actual_params = params or path_or_params or {}
            if isinstance(actual_params, str):
                # path_or_params is actually path string, params kwarg has params
                actual_params = params or {}
            captured_params.update(actual_params)
            return {"indicator_id": "CPIAUCSL", "releases": [], "ttl_seconds": 60}

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=_capture_get):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", limit=999)
            )

        assert captured_params.get("limit") == 60

    def test_404_returns_no_match_found(self, set_vm102_url):
        from tools.proxies import vm102_indicator_releases as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("404 not found")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="BOGUS")
            )

        assert result.releases == []
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.NO_MATCH_FOUND in fm_codes


# =========================================================================
# vm102_indicator_distribution
# =========================================================================

class TestVm102IndicatorDistribution:

    def test_happy_path_maps_fields(self, set_vm102_url):
        from tools.proxies import vm102_indicator_distribution as proxy

        fake_response = {
            "indicator_id": "CPIAUCSL",
            "surprise_distribution": {
                "bins": [
                    {"lower": -0.5, "upper": 0.0, "count": 12},
                    {"lower": 0.0, "upper": 0.5, "count": 18},
                ],
                "p10": -0.3,
                "p50": 0.1,
                "p90": 0.4,
            },
            "current_release_percentile": 72.5,
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 1800,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        assert result.indicator_id == "CPIAUCSL"
        assert result.current_release_percentile == 72.5
        assert result.surprise_distribution["p50"] == 0.1
        assert len(result.surprise_distribution["bins"]) == 2
        assert result.ttl_seconds == 1800
        assert _has_provenance(result)

    def test_404_returns_no_match_found(self, set_vm102_url):
        from tools.proxies import vm102_indicator_distribution as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("HTTP 404 not found")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="BOGUS")
            )

        assert result.surprise_distribution is None
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.NO_MATCH_FOUND in fm_codes


# =========================================================================
# vm102_indicator_asset_exposure
# =========================================================================

class TestVm102IndicatorAssetExposure:

    def test_happy_path_maps_paired_assets(self, set_vm102_url):
        from tools.proxies import vm102_indicator_asset_exposure as proxy

        fake_response = {
            "indicator_id": "CPIAUCSL",
            "computed_at": "2026-06-22T10:00:00Z",
            "window_trading_days": 200,
            "paired_assets": [
                {
                    "asset_id": "DXY",
                    "asset_label": "USD Index",
                    "default_direction": "POS",
                    "rolling_correlation": 0.62,
                    "sign": "POS",
                    "strength_score": 62,
                },
                {
                    "asset_id": "XAUUSD",
                    "asset_label": "Gold",
                    "default_direction": "NEG",
                    "rolling_correlation": None,  # OHLC unavailable — graceful degrade
                    "sign": "NEG",
                    "strength_score": 0,
                },
            ],
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 3600,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        assert result.indicator_id == "CPIAUCSL"
        assert result.window_trading_days == 200
        assert len(result.paired_assets) == 2
        assert result.paired_assets[0]["strength_score"] == 62
        assert result.paired_assets[1]["rolling_correlation"] is None
        assert result.ttl_seconds == 3600
        assert _has_provenance(result)

    def test_partial_data_failure_mode_declared(self, set_vm102_url):
        """PARTIAL_DATA failure mode should be declared (null correlations allowed)."""
        from tools.proxies import vm102_indicator_asset_exposure as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        # Happy path but we verify PARTIAL_DATA is in declared_failure_modes
        fake_response = {
            "indicator_id": "CPIAUCSL",
            "computed_at": "2026-06-22T10:00:00Z",
            "window_trading_days": 200,
            "paired_assets": [],
            "cached_at": "2026-06-22T10:00:00Z",
            "ttl_seconds": 3600,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL")
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.PARTIAL_DATA in fm_codes


# =========================================================================
# vm102_indicator_event_study
# =========================================================================

class TestVm102IndicatorEventStudy:

    def test_happy_path_maps_curves(self, set_vm102_url):
        from tools.proxies import vm102_indicator_event_study as proxy

        fake_response = {
            "envelope": {
                "tool_id": "vm102_event_study",
                "confidence": "high",
                "provenance": {"sample_size": 25},
                "latency_ms": 120,
            },
            "result": {
                "curves": [
                    {
                        "asset_id": "gold",
                        "points": [
                            {"day": -2, "mean_return": -0.001},
                            {"day": 0, "mean_return": 0.005},
                            {"day": 3, "mean_return": 0.012},
                        ],
                    }
                ],
                "sample_size": 25,
                "period": "2010-01-01–2026-01-01",
            },
            "error": None,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(
                    indicator_id="CPIAUCSL",
                    threshold=0.2,
                    direction="beat",
                    assets="gold",
                )
            )

        assert result.indicator_id == "CPIAUCSL"
        assert len(result.curves) == 1
        assert result.curves[0]["asset_id"] == "gold"
        assert result.sample_size == 25
        assert result.error is None
        assert _has_provenance(result)

    def test_sample_too_small_returns_insufficient_context(self, set_vm102_url):
        """EventStudySampleTooSmall (HTTP 200 + error field) → INSUFFICIENT_CONTEXT."""
        from tools.proxies import vm102_indicator_event_study as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        fake_response = {
            "envelope": {"tool_id": "vm102_event_study", "confidence": "low", "provenance": {}, "latency_ms": 30},
            "result": None,
            "error": {"code": "EventStudySampleTooSmall", "meta": {"N": 0, "threshold": 0.9}},
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", threshold=0.9, assets="gold")
            )

        assert result.curves == []
        assert result.error is not None
        assert result.error["code"] == "EventStudySampleTooSmall"
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.INSUFFICIENT_CONTEXT in fm_codes

    def test_400_returns_validation_failed(self, set_vm102_url):
        """HTTP 400 from VM102 (UnknownAsset/TooManyAssets) → VALIDATION_FAILED."""
        from tools.proxies import vm102_indicator_event_study as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("400 Bad Request UnknownAsset")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", assets="zzz_not_real")
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.VALIDATION_FAILED in fm_codes

    def test_timeout_returns_upstream_timeout(self, set_vm102_url):
        from tools.proxies import vm102_indicator_event_study as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("Connection timeout")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", assets="gold")
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.UPSTREAM_TIMEOUT in fm_codes


# =========================================================================
# vm102_indicator_correlations
# =========================================================================

class TestVm102IndicatorCorrelations:

    def test_happy_path_maps_series(self, set_vm102_url):
        from tools.proxies import vm102_indicator_correlations as proxy

        fake_response = {
            "envelope": {
                "tool_id": "vm102_correlations",
                "confidence": "high",
                "provenance": {"sample_size": 200, "window": 200},
                "latency_ms": 95,
            },
            "result": {
                "series": [
                    {"date": "2026-01-10", "corr": 0.58},
                    {"date": "2026-02-10", "corr": 0.62},
                ]
            },
            "error": None,
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", asset="gold", window=200)
            )

        assert result.indicator_id == "CPIAUCSL"
        assert result.asset == "gold"
        assert result.window == 200
        assert len(result.series) == 2
        assert all(-1.0 <= p["corr"] <= 1.0 for p in result.series)
        assert result.error is None
        assert _has_provenance(result)

    def test_bad_window_returns_validation_failed_without_http_call(self, set_vm102_url):
        """Window not in {50,100,200,500} → VALIDATION_FAILED, no HTTP call made."""
        from tools.proxies import vm102_indicator_correlations as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        call_count = 0

        async def _should_not_be_called(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {}

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=_should_not_be_called):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", asset="gold", window=999)
            )

        assert call_count == 0, "HTTP call must not be made for invalid window"
        assert result.series == []
        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.VALIDATION_FAILED in fm_codes

    def test_unknown_asset_returns_validation_failed(self, set_vm102_url):
        """HTTP 400 from VM102 (UnknownAsset) → VALIDATION_FAILED."""
        from tools.proxies import vm102_indicator_correlations as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("400 UnknownAsset")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", asset="zzz", window=200)
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.VALIDATION_FAILED in fm_codes

    def test_domain_error_response_surfaces_error_field(self, set_vm102_url):
        """VM102 returns error dict in envelope → result.error is populated."""
        from tools.proxies import vm102_indicator_correlations as proxy

        fake_response = {
            "envelope": {"tool_id": "vm102_correlations", "confidence": "low", "provenance": {}, "latency_ms": 10},
            "result": None,
            "error": {"code": "UnknownIndicator", "meta": {"indicator": "BOGUS"}},
        }

        with patch("fingpt_core.clients.vm102_client.VM102Client.get", new=AsyncMock(return_value=fake_response)):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="BOGUS", asset="gold", window=200)
            )

        assert result.error is not None
        assert result.error["code"] == "UnknownIndicator"
        assert result.series == []

    def test_timeout_returns_upstream_timeout(self, set_vm102_url):
        from tools.proxies import vm102_indicator_correlations as proxy
        from fingpt_core.contracts.failure_modes import FailureModeCode

        with patch(
            "fingpt_core.clients.vm102_client.VM102Client.get",
            new=AsyncMock(side_effect=Exception("Connection timeout")),
        ):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                proxy.run_async(indicator_id="CPIAUCSL", asset="gold", window=200)
            )

        fm_codes = [fm.code for fm in result.provenance.declared_failure_modes]
        assert FailureModeCode.UPSTREAM_TIMEOUT in fm_codes


# =========================================================================
# Cross-proxy: no-fallback check
# =========================================================================

class TestNoFallbackDefaults:

    def test_vm102_url_unset_raises_runtime_error(self, monkeypatch):
        """VM102_API_URL unset → RuntimeError (no fallback defaults)."""
        monkeypatch.delenv("VM102_API_URL", raising=False)

        # Reimport to avoid cached env
        import importlib
        import fingpt_core.clients.vm102_client as _m
        importlib.reload(_m)

        with pytest.raises(RuntimeError, match="VM102_API_URL"):
            _m.VM102Client()
