"""Phase 87 Plan 06 (Wave 3) — Phase 86 ``/event-study`` analogue client.

Calls the Phase 86 cross-asset event-study endpoint with the current
release's surprise + direction + a fixed asset basket
(``DXY``, ``XAUUSD``, ``SPX``) and returns up to ``top_k`` past releases
as historical analogues. Degrades gracefully on Phase 86 failure — the
agent persists the envelope with ``degraded=True`` rather than raising.

Per project lock: ``vm102_base_url`` is required (no fallback default,
no ``os.getenv("X", "default")`` pattern). The agent injects the URL at
construction time from an env-driven config.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoricalAnalogue:
    """One row in the top-K analogues returned to the agent.

    Attributes:
        release_id:      Phase 83 release uuid (string form for JSON).
        release_date:    ISO-8601 date of the analogue release.
        indicator_id:    FRED-style series id (e.g. "CPIAUCSL").
        surprise:        Past release's surprise value (signed).
        sample_size:     Phase 86 envelope sample_size for the curve.
        evidence_period: ISO date range (e.g. "2020-01-01/2025-01-01").
    """

    release_id: str
    release_date: str
    indicator_id: str
    surprise: float
    sample_size: int
    evidence_period: str


class EventStudyAnalogueClient:
    """HTTP client wrapping Phase 86 ``/api/v2/indicator/<id>/event-study``.

    Returns up to ``top_k`` historical analogues. On any failure (HTTP
    non-200, network error, malformed JSON), returns an empty list and
    logs a warning — the agent treats empty as a degraded path.
    """

    DEFAULT_ASSETS: tuple[str, ...] = ("DXY", "XAUUSD", "SPX")

    def __init__(
        self,
        vm102_base_url: str,
        *,
        timeout_s: float = 5.0,
    ) -> None:
        if not vm102_base_url:
            raise RuntimeError(
                "VM102 base URL required — env-driven, no default. "
                "Set VM102_BASE_URL in the VM107 docker-compose env."
            )
        self._base = vm102_base_url.rstrip("/")
        self._timeout_s = float(timeout_s)
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout_s)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_analogues(
        self,
        *,
        indicator_id: str,
        surprise: float,
        assets: Iterable[str] | None = None,
        pre: int = 5,
        post: int = 10,
        top_k: int = 3,
    ) -> list[HistoricalAnalogue]:
        """Return up to ``top_k`` historical analogue releases.

        Args:
            indicator_id: FRED series id of the just-released indicator.
            surprise:     Current release's surprise (signed); direction
                          (beat/miss) is derived from the sign.
            assets:       Asset basket for the event-study (default
                          DXY/XAUUSD/SPX per LOCK-2).
            pre:          Bars of pre-event lookback.
            post:         Bars of post-event lookahead.
            top_k:        Maximum analogues to return.

        Returns:
            List of ``HistoricalAnalogue`` (empty on any failure).
        """
        asset_list = list(assets) if assets is not None else list(self.DEFAULT_ASSETS)
        direction = "beat" if surprise >= 0 else "miss"
        url = f"{self._base}/api/v2/indicator/{indicator_id}/event-study"
        params = {
            "threshold": abs(float(surprise)),
            "direction": direction,
            "assets": ",".join(asset_list),
            "pre": int(pre),
            "post": int(post),
        }

        client = self._get_client()
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                {
                    "event": "event_study_request_failed",
                    "indicator_id": indicator_id,
                    "error": str(exc),
                }
            )
            return []

        if resp.status_code != 200:
            logger.warning(
                {
                    "event": "event_study_non_200",
                    "indicator_id": indicator_id,
                    "status_code": resp.status_code,
                }
            )
            return []

        try:
            payload = resp.json()
        except ValueError as exc:
            logger.warning(
                {
                    "event": "event_study_json_decode_failed",
                    "indicator_id": indicator_id,
                    "error": str(exc),
                }
            )
            return []

        envelope = payload.get("envelope", {}) or {}
        result = payload.get("result", {}) or {}
        curves = result.get("curves", []) or []
        releases: list[dict] = []
        if curves:
            first_curve = curves[0] or {}
            releases = first_curve.get("releases", []) or []

        analogues: list[HistoricalAnalogue] = []
        for r in releases[: int(top_k)]:
            try:
                analogues.append(
                    HistoricalAnalogue(
                        release_id=str(r.get("release_id", "")),
                        release_date=str(r.get("release_date", "")),
                        indicator_id=indicator_id,
                        surprise=float(r.get("surprise", 0.0)),
                        sample_size=int(envelope.get("sample_size", 0)),
                        evidence_period=str(envelope.get("period", "")),
                    )
                )
            except (TypeError, ValueError) as exc:  # pragma: no cover — defensive
                logger.warning(
                    {
                        "event": "event_study_release_malformed",
                        "indicator_id": indicator_id,
                        "release": r,
                        "error": str(exc),
                    }
                )
                continue
        return analogues
