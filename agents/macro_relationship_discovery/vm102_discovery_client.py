"""Phase 89.2 — synchronous VM102 client for the nightly discovery scan loop.

Implements the duck-typed interface that
:class:`core.discovery.correlation_scanner.CorrelationScanner` expects:

    indicator_correlations(indicator_a: str, indicator_b: str, window_months: int)
        -> {r, p_value, sample_size, period_start, period_end}

    indicator_lead_lag(indicator_a: str, indicator_b: str, max_lag_months: int)
        -> {peak_lag, peak_r, p_value}

VM102 endpoints (Phase 86 macro_analytics router):
    GET /api/v2/analytics/indicator/{id}/correlations?asset={slug}&window={N}
    GET /api/v2/analytics/indicator/{id}/lead-lag?asset={slug}

Design constraints (per 89.2-RESEARCH.md):

- ``VM102_API_URL`` + ``VM102_SERVICE_JWT`` are read fail-fast on
  instantiation. No ``os.getenv("X", "default")`` patterns — missing env
  raises :class:`KeyError` per the project env-driven-no-fallbacks lock.
- ``CorrelationScanner`` is synchronous; we do NOT reuse the async tool proxy
  at ``tools/proxies/vm102_indicator_correlations.py`` (that path is for the
  agent-runner tool dispatch, not background scans). Direct ``requests``
  call instead.
- ``window_months`` is converted to days and snapped to the nearest member of
  the VM102-allowed set ``{50, 100, 200, 500}`` (Pitfall 5: VM102 422s any
  other window value).
- Missing ``p_value`` in either response defaults to ``1.0`` — guarantees the
  threshold filter rejects the pair (conservative per RESEARCH Pitfall 5).
- ``timeout=30`` per HTTP call (long enough for VM102 rolling-window compute,
  short enough that a hung pair doesn't block the whole nightly scan).

The class is designed so tests can inject ``session`` and ``api_url`` /
``jwt`` to avoid real HTTP — mirrors the dependency-injection pattern from
``agents/macro_historical_analyst/agent.py``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# VM102 only accepts these window-day values; ``window_months`` is snapped.
_ALLOWED_WINDOW_DAYS: tuple[int, ...] = (50, 100, 200, 500)

# Per-call HTTP timeout (seconds). Tuned for VM102 rolling-window compute.
_DEFAULT_TIMEOUT_S: int = 30


def _snap_window_months_to_days(window_months: int) -> int:
    """Convert ``window_months`` → days and snap to the nearest allowed value.

    VM102 422s any ``window`` outside ``{50, 100, 200, 500}``. We pick the
    nearest absolute-difference member so callers can pass any
    ``window_months`` without knowing the server-side allowed set.
    """
    target_days = window_months * 30
    return min(_ALLOWED_WINDOW_DAYS, key=lambda w: abs(w - target_days))


class Vm102DiscoveryClient:
    """Synchronous VM102 client matching the CorrelationScanner duck-type.

    Args:
        api_url: Override ``VM102_API_URL`` (testing only).
        jwt:     Override ``VM102_SERVICE_JWT`` (testing only).
        session: Override the ``requests.Session`` (testing only — inject a
                 mock to avoid real HTTP).
        timeout: Per-call HTTP timeout in seconds (default 30).

    Raises:
        KeyError: If ``VM102_API_URL`` or ``VM102_SERVICE_JWT`` is unset and
                  no override is supplied (fail-fast per env-driven config
                  lock).
    """

    def __init__(
        self,
        api_url: str | None = None,
        jwt: str | None = None,
        session: requests.Session | None = None,
        timeout: int = _DEFAULT_TIMEOUT_S,
    ) -> None:
        # Fail-fast: ``os.environ["X"]`` raises KeyError on missing env.
        self._api_url = (api_url if api_url is not None else os.environ["VM102_API_URL"]).rstrip("/")
        self._jwt = jwt if jwt is not None else os.environ["VM102_SERVICE_JWT"]
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._jwt}",
            "Accept": "application/json",
        }

    def indicator_correlations(
        self,
        indicator_a: str,
        indicator_b: str,
        window_months: int,
    ) -> dict[str, Any]:
        """Fetch rolling Pearson correlation between an indicator and an asset.

        VM102 returns a rolling time-series; we normalise to the duck-typed
        single-stat dict CorrelationScanner expects by taking the latest row
        in ``result.series`` as the representative ``r`` value, and using
        ``envelope.provenance.sample_size`` (falls back to ``len(series)``)
        for ``sample_size``.

        Args:
            indicator_a:   FRED indicator code (e.g. ``"CPIAUCSL"``).
            indicator_b:   Asset slug (e.g. ``"gold"``) — VM102 only supports
                           indicator-vs-asset, not indicator-vs-indicator.
            window_months: Window in months; snapped to nearest of
                           ``{50, 100, 200, 500}`` days.

        Returns:
            ``{r, p_value, sample_size, period_start, period_end}`` —
            shape matches what
            :meth:`core.discovery.correlation_scanner.CorrelationScanner._evaluate_pair`
            reads via ``corr_result.get(...)``.

            On absent ``p_value`` in response: defaults to ``1.0`` so the
            threshold filter rejects the pair (Pitfall 5 — conservative).
        """
        window_days = _snap_window_months_to_days(window_months)
        url = f"{self._api_url}/api/v2/analytics/indicator/{indicator_a}/correlations"
        params = {"asset": indicator_b, "window": window_days}

        resp = self._session.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json() or {}

        envelope_meta = body.get("envelope") or {}
        result = body.get("result") or {}
        series: list[dict[str, Any]] = result.get("series") or []

        # Latest row is the representative r value for the window.
        latest = series[-1] if series else {}
        r = float(latest.get("corr", 0.0))

        # p_value comes from the envelope provenance when VM102 includes it,
        # otherwise default to 1.0 (threshold-reject — RESEARCH Pitfall 5).
        provenance = envelope_meta.get("provenance") or {}
        p_value = float(provenance.get("p_value", 1.0))

        sample_size = int(provenance.get("sample_size", len(series)))

        # Period bounds — first/last series date when present.
        period_start = ""
        period_end = ""
        if series:
            period_start = str(series[0].get("date", ""))
            period_end = str(series[-1].get("date", ""))

        return {
            "r": r,
            "p_value": p_value,
            "sample_size": sample_size,
            "period_start": period_start,
            "period_end": period_end,
        }

    def indicator_lead_lag(
        self,
        indicator_a: str,
        indicator_b: str,
        max_lag_months: int,
    ) -> dict[str, Any]:
        """Fetch lead-lag table and return the peak-|corr| row reshaped.

        VM102 returns a small table (typically 4 rows) of (lag_months, corr,
        p_value) entries. We pick the row with the largest absolute
        correlation as the "peak" — matches what
        :meth:`CorrelationScanner._evaluate_pair` expects via
        ``lag_result.get("peak_lag", 0.0)``.

        Args:
            indicator_a:    FRED indicator code.
            indicator_b:    Asset slug.
            max_lag_months: Hint for VM102 (not used in URL — VM102 lead-lag
                            endpoint computes a fixed lag set; the caller's
                            requested lag is ignored server-side per Phase 86).

        Returns:
            ``{peak_lag, peak_r, p_value}``. On empty/missing table:
            ``peak_lag=0.0``, ``peak_r=0.0``, ``p_value=1.0``
            (threshold-reject — RESEARCH Pitfall 5).
        """
        # ``max_lag_months`` retained in the signature to match the duck-type
        # CorrelationScanner expects; not consumed in the URL.
        del max_lag_months

        url = f"{self._api_url}/api/v2/analytics/indicator/{indicator_a}/lead-lag"
        params = {"asset": indicator_b}

        resp = self._session.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json() or {}

        result = body.get("result") or {}
        table: list[dict[str, Any]] = result.get("table") or []

        if not table:
            return {"peak_lag": 0.0, "peak_r": 0.0, "p_value": 1.0}

        # Pick the row with the largest absolute correlation as the peak.
        peak_row = max(table, key=lambda row: abs(float(row.get("corr", 0.0))))
        peak_lag = float(peak_row.get("lag_months", 0.0))
        peak_r = float(peak_row.get("corr", 0.0))
        p_value = float(peak_row.get("p_value", 1.0))

        return {
            "peak_lag": peak_lag,
            "peak_r": peak_r,
            "p_value": p_value,
        }
