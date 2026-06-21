"""Phase 89 Wave 2 — counterfactual forecast client.

Decision 12: wraps Phase 90 Layer 4 /forecast/market-impact when the env var
PHASE_90_FORECAST_URL is set AND the health-check endpoint returns 200.

Pitfall 5: When Phase 90 is absent (env var unset OR health check fails OR 503),
falls back to Phase 86 event-study via VM102 /indicator/event-study. NEVER
silently errors. If BOTH paths fail, raises ForecastUnavailable — the caller
translates to a ForecastUnavailableResponse (never fabricated numbers).

Per project locks:
  - NO os.getenv("X", "default") — env-driven, fail-fast
  - PHASE_90_FORECAST_URL unset means Phase 90 is not shipped; use fallback
  - VM102_URL must be set for the fallback path; raises if missing
  - _call_event_study is the sole patchable seam for tests
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, timezone, datetime
from typing import Literal

logger = logging.getLogger(__name__)

# Health-check timeout (seconds) — short; we don't want to block the fallback
_PHASE_90_HEALTH_TIMEOUT_S = 2


# ─── Custom exception ─────────────────────────────────────────────────────────

class ForecastUnavailable(Exception):
    """Raised when both Phase 90 AND Phase 86 event-study paths are unavailable.

    Per Pitfall 5: the caller must NOT fabricate numbers. Translate to
    ForecastUnavailableResponse with status="forecast_unavailable".
    """


# ─── Patchable seams ─────────────────────────────────────────────────────────

def _probe_phase90(forecast_url: str) -> bool:
    """Probe Phase 90 health endpoint. Returns True if available.

    This is a separate patchable seam so tests can mock Phase 90 up/down
    independently of the full requests library.

    Args:
        forecast_url: Base URL from PHASE_90_FORECAST_URL env var.

    Returns:
        True if GET /health returns 200 within _PHASE_90_HEALTH_TIMEOUT_S.
        False if any exception (ConnectionError, Timeout, etc.) or non-200.
    """
    try:
        import requests  # type: ignore[import]
        resp = requests.get(
            f"{forecast_url.rstrip('/')}/health",
            timeout=_PHASE_90_HEALTH_TIMEOUT_S,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _call_phase90_forecast(
    forecast_url: str,
    indicator: str,
    hypothetical: float,
    analogue_release_ids: list[str],
    asset_keys: list[str],
    windows: list[str],
) -> dict:
    """POST to Phase 90 /forecast/market-impact.

    Args:
        forecast_url: Base URL from PHASE_90_FORECAST_URL.
        indicator: FRED indicator ID.
        hypothetical: The hypothetical surprise value.
        analogue_release_ids: IDs of analogues to include.
        asset_keys: Assets to forecast (DXY, Gold, SPX, UST10Y).
        windows: Time windows (T+1h, T+1d, T+1w).

    Returns:
        Phase 90 response dict with per_asset expected-move data.

    Raises:
        RuntimeError: On non-200 or network error.
    """
    import requests  # type: ignore[import]
    payload = {
        "indicator": indicator,
        "hypothetical_surprise": hypothetical,
        "analogue_release_ids": analogue_release_ids,
        "asset_keys": asset_keys,
        "windows": windows,
    }
    resp = requests.post(
        f"{forecast_url.rstrip('/')}/forecast/market-impact",
        json=payload,
        timeout=30,
    )
    if resp.status_code == 503:
        raise RuntimeError(f"Phase 90 /forecast/market-impact returned 503 — service unavailable")
    resp.raise_for_status()
    data = resp.json()
    data.setdefault("forecast_source", "phase_90_layer_4")
    return data


def _call_event_study(
    indicator: str,
    analogue_release_ids: list[str],
    asset_keys: list[str],
    windows: list[str],
) -> dict:
    """Call Phase 86 /indicator/event-study via VM102.

    This is the patchable seam for tests. Tests mock
    `core.counterfactual.forecast_client._call_event_study`.

    Args:
        indicator: FRED indicator ID.
        analogue_release_ids: Release IDs to include in event-study.
        asset_keys: Assets to analyse.
        windows: Time windows.

    Returns:
        dict with per_asset: {asset: {window: {mean_pct, ci_low, ci_high, sample_size}}}
        plus `forecast_source: "phase_86_event_study_fallback"`.

    Raises:
        ForecastUnavailable: If VM102 is unreachable or returns error.
        RuntimeError: If VM102_URL env var not set.
    """
    vm102_url = os.environ.get("VM102_URL")
    if not vm102_url:
        raise RuntimeError(
            "forecast_client: VM102_URL environment variable not set. "
            "Cannot call Phase 86 event-study fallback. "
            "Set VM102_URL=<url> (no fallback per project lock)."
        )

    try:
        import requests  # type: ignore[import]
        payload = {
            "indicator_id": indicator,
            "analogue_release_ids": analogue_release_ids,
            "asset_keys": asset_keys,
            "windows": windows,
        }
        resp = requests.post(
            f"{vm102_url.rstrip('/')}/indicator/event-study",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        data["forecast_source"] = "phase_86_event_study_fallback"
        return data
    except Exception as exc:  # noqa: BLE001
        raise ForecastUnavailable(
            f"forecast_client: Phase 86 event-study also unavailable: {exc}"
        ) from exc


# ─── Public API ──────────────────────────────────────────────────────────────

def forecast_market_impact(
    indicator: str,
    hypothetical: float,
    analogues: list[dict],
    asset_keys: list[str],
    windows: list[str],
) -> dict:
    """Compute expected market impact of the hypothetical scenario.

    Decision 12 path selection:
      1. If PHASE_90_FORECAST_URL set AND health probe returns 200:
         → POST to Phase 90 /forecast/market-impact (preferred path)
      2. Else (env unset OR health probe fails OR Phase 90 returns 503):
         → call Phase 86 /indicator/event-study on the analogue set (fallback)
      3. If BOTH paths fail:
         → raise ForecastUnavailable (caller converts to ForecastUnavailableResponse)

    Per Pitfall 5: NEVER return fabricated numbers. If both paths fail, raise
    so the caller can surface an honest "forecast_unavailable" response.

    Args:
        indicator: FRED indicator ID.
        hypothetical: User's hypothetical surprise value.
        analogues: List of analogue dicts from query_analogues (must have release_id).
        asset_keys: Assets to include in the expected-move table.
        windows: Time windows (e.g. ["T+1h", "T+1d", "T+1w"]).

    Returns:
        dict with keys:
          - per_asset: {asset: {window: {mean_pct, ci_low, ci_high, sample_size}}}
          - forecast_source: "phase_90_layer_4" OR "phase_86_event_study_fallback"

    Raises:
        ForecastUnavailable: If both Phase 90 + Phase 86 are unavailable.
    """
    analogue_release_ids = [
        a.get("release_id") or a.get("id") or str(uuid.uuid4())
        for a in analogues
    ]

    # ── Decision 12: try Phase 90 first ──────────────────────────────────────
    phase90_url = os.environ.get("PHASE_90_FORECAST_URL")  # NO default per project lock

    if phase90_url:
        # Probe Phase 90 health before committing to the request
        if _probe_phase90(phase90_url):
            logger.info(
                "forecast_client.using_phase90",
                extra={"indicator": indicator, "url": phase90_url},
            )
            try:
                result = _call_phase90_forecast(
                    forecast_url=phase90_url,
                    indicator=indicator,
                    hypothetical=hypothetical,
                    analogue_release_ids=analogue_release_ids,
                    asset_keys=asset_keys,
                    windows=windows,
                )
                return result
            except RuntimeError as exc:
                logger.warning(
                    "forecast_client.phase90_failed_falling_back",
                    extra={"indicator": indicator, "error": str(exc)},
                )
                # Fall through to Phase 86 fallback
        else:
            logger.info(
                "forecast_client.phase90_unavailable_falling_back",
                extra={"indicator": indicator, "url": phase90_url},
            )
    else:
        logger.info(
            "forecast_client.phase90_env_unset_using_fallback",
            extra={"indicator": indicator},
        )

    # ── Pitfall 5 fallback: Phase 86 event-study ─────────────────────────────
    logger.info(
        "forecast_client.using_phase86_fallback",
        extra={"indicator": indicator, "analogue_count": len(analogues)},
    )
    # ForecastUnavailable propagates up if Phase 86 also fails
    return _call_event_study(
        indicator=indicator,
        analogue_release_ids=analogue_release_ids,
        asset_keys=asset_keys,
        windows=windows,
    )
