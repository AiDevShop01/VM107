"""Phase 87 Wave 1 — VM102 correlation augmentation for the macro graph seed.

Per project lock — env-driven config, fail-fast (no `os.getenv("X", "default")`).

The augmenter is best-effort by LOCK-1 — the seed YAML is hand-curated and the
correlation call is bonus. Failures degrade gracefully: the YAML fallback edge
is returned with `degraded=True` so the load can continue and Mission Control
can show estimated vs measured edges.

Per Open Question 1 (RESEARCH §"Open Questions"): VM102's public correlations
endpoint takes `asset=<SYMBOL>` (Phase 86 contract); we attempt
`?indicator=<dst>` first in case Phase 86 added the indicator-to-indicator
shape. Any non-200 is treated as "degraded augmentation" — the YAML hand
value rides.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AffectsEdge:
    """An :MacroIndicator-[:AFFECTS]->:MacroIndicator edge."""

    source: str
    target: str
    hop_order: int
    strength: float
    confidence: float
    sample_size: int
    evidence_period: str
    curation_source: str = "seed_yaml"
    degraded: bool = False


@dataclass(frozen=True)
class DrivesEdge:
    """An :MacroIndicator-[:DRIVES]->:Asset edge.

    `direction` carries the sign; `strength` is unsigned in [0, 1] per the
    Plan 87-02 schema contract.
    """

    source: str
    target: str
    direction: str  # 'positive' | 'negative' | 'mixed' | 'neutral'
    strength: float
    confidence: float
    sample_size: int
    evidence_period: str
    curation_source: str = "seed_yaml"
    degraded: bool = False


class CorrelationAugmenter:
    """Best-effort VM102 augmentation.

    Per LOCK-1 the seed is hand-curated; augmentation is bonus.  Failures
    degrade gracefully — caller persists the YAML fallback values and tags
    the edge `degraded=True` so a stakeholder dashboard can show which edges
    are estimated vs measured.
    """

    def __init__(self, vm102_base_url: str, *, timeout_s: float = 5.0):
        if not vm102_base_url:
            raise RuntimeError(
                "VM102_BASE_URL is required — env-driven config, no default"
            )
        self._base_url = vm102_base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CorrelationAugmenter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── AFFECTS edge augmentation ────────────────────────────────────────────
    def augment_affects(
        self,
        *,
        source: str,
        target: str,
        window_days: int = 1095,
        yaml_fallback: AffectsEdge,
    ) -> AffectsEdge:
        url = f"{self._base_url}/api/v2/indicator/{source}/correlations"
        try:
            resp = self._client.get(
                url, params={"indicator": target, "window": window_days}
            )
            if resp.status_code != 200:
                # Open Question 1 — public endpoint may be asset-only.
                logger.info(
                    "VM102 indicator-correlation %s->%s degraded (HTTP %d)",
                    source,
                    target,
                    resp.status_code,
                )
                return replace(yaml_fallback, degraded=True, curation_source="seed_yaml")
            payload = resp.json()
            envelope = payload.get("envelope", {}) or {}
            points = (payload.get("result", {}) or {}).get("points", []) or []
            if not points:
                return replace(yaml_fallback, degraded=True)
            latest_corr = points[-1].get("corr", yaml_fallback.strength)
            return replace(
                yaml_fallback,
                strength=float(latest_corr),
                confidence=float(
                    envelope.get("confidence", yaml_fallback.confidence)
                ),
                sample_size=int(
                    envelope.get("sample_size", yaml_fallback.sample_size)
                ),
                evidence_period=str(
                    envelope.get("period", yaml_fallback.evidence_period)
                ),
                curation_source="vm102_correlation",
                degraded=False,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Augmenter (AFFECTS) failed for %s->%s: %s", source, target, exc
            )
            return replace(yaml_fallback, degraded=True)

    # ── DRIVES edge augmentation ─────────────────────────────────────────────
    def augment_drives(
        self,
        *,
        source: str,
        target_symbol: str,
        window_days: int = 1095,
        yaml_fallback: DrivesEdge,
    ) -> DrivesEdge:
        url = f"{self._base_url}/api/v2/indicator/{source}/correlations"
        try:
            resp = self._client.get(
                url, params={"asset": target_symbol, "window": window_days}
            )
            if resp.status_code != 200:
                logger.info(
                    "VM102 asset-correlation %s->%s degraded (HTTP %d)",
                    source,
                    target_symbol,
                    resp.status_code,
                )
                return replace(yaml_fallback, degraded=True)
            payload = resp.json()
            envelope = payload.get("envelope", {}) or {}
            points = (payload.get("result", {}) or {}).get("points", []) or []
            if not points:
                return replace(yaml_fallback, degraded=True)
            latest_corr = points[-1].get("corr", yaml_fallback.strength)
            return replace(
                yaml_fallback,
                strength=abs(float(latest_corr)),  # DRIVES.strength in [0, 1]
                confidence=float(
                    envelope.get("confidence", yaml_fallback.confidence)
                ),
                sample_size=int(
                    envelope.get("sample_size", yaml_fallback.sample_size)
                ),
                evidence_period=str(
                    envelope.get("period", yaml_fallback.evidence_period)
                ),
                curation_source="vm102_correlation",
                degraded=False,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Augmenter (DRIVES) failed for %s->%s: %s",
                source,
                target_symbol,
                exc,
            )
            return replace(yaml_fallback, degraded=True)
