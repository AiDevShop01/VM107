"""Phase 94-06 — ThemeMonitor agent (narrative consumer of theme engine).

Reads :class:`Theme` objects produced by the deterministic
:class:`MacroThemeEngine` (94-05), ranks them by ``Strength × Confidence``
per §H.4, and emits a :class:`ThemeMonitorSection` clipped to 5..7 themes
for dashboard display per §H.4.

Per §F + §J locks:
* Narrative-only — agent does NOT mutate theme strength or state.
* Ranking is computed from the (theme, confidence) pairs supplied by
  the caller; the agent does not introspect raw evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.provenance import ProvenanceObject
from contracts.economic_intelligence.themes import Theme, ThemeMonitorSection, ThemeState

logger = logging.getLogger(__name__)

_DASHBOARD_MIN = 5
_DASHBOARD_MAX = 7


class ThemeMonitor:
    """Consumes Theme objects + confidences; emits ThemeMonitorSection."""

    AGENT_ID = "vm107.theme_monitor"
    SECTION_ID = "themes"

    def invoke(
        self,
        themes_with_confidence: Iterable[tuple[Theme, float]],
        country: str,
        snapshot_id: str | None = None,
        version: int = 1,
    ) -> ThemeMonitorSection:
        """Rank + clip to dashboard size; emit ThemeMonitorSection.

        ``themes_with_confidence`` is an iterable of ``(Theme, confidence)``
        pairs. Confidence is in ``[0, 1]`` and is NOT a Theme field — it
        comes from upstream evidence quality scoring per §H.4.
        """
        pairs = [
            (theme, float(conf))
            for theme, conf in themes_with_confidence
            if theme.state is not ThemeState.ARCHIVED
        ]
        # Strength × Confidence ranking per §H.4. Stable sort on (-score, theme_id).
        pairs.sort(key=lambda tc: (-(tc[0].strength * tc[1]), tc[0].theme_id))
        # Clip to dashboard range — never below 5 unless input is smaller,
        # never above 7.
        clipped = pairs[:_DASHBOARD_MAX]
        themes = [theme for theme, _ in clipped]
        # Confidence carried into section envelope as the weighted mean.
        section_confidence = _weighted_mean(clipped) if clipped else 0.0
        section_id = self.SECTION_ID
        return ThemeMonitorSection(
            section_id=section_id,
            version=version,
            generated_at=datetime.now(timezone.utc),
            snapshot_id=snapshot_id or f"themes:{country}",
            freshness_seconds=0,
            confidence=section_confidence,
            status=SectionStatus.READY if themes else SectionStatus.UNAVAILABLE,
            agent=self.AGENT_ID,
            execution_time_ms=1,
            citations=[f"ref:theme:{t.theme_id}" for t in themes],
            limitations=_derive_limitations(pairs, themes),
            depends_on=["theme_engine"],
            provenance=ProvenanceObject(
                source_event_ids=[],
                weights_version="theme_engine_v1",
                model_version="na",
                prompt_version="na",
                upstream_sections=["themes"],
                data_versions={},
            ),
            themes=themes,
        )


# ─────────────────────────────────────────────────────────────── helpers


def _weighted_mean(pairs: list[tuple[Theme, float]]) -> float:
    total_weight = sum(t.strength for t, _ in pairs) or 1.0
    return sum(t.strength * c for t, c in pairs) / total_weight


def _derive_limitations(all_pairs, displayed_themes) -> list[str]:
    lims: list[str] = []
    n_total = len(all_pairs)
    n_displayed = len(displayed_themes)
    if n_displayed < _DASHBOARD_MIN and n_total > 0:
        lims.append(
            f"only {n_displayed} active themes — below dashboard minimum of {_DASHBOARD_MIN}"
        )
    if n_total > _DASHBOARD_MAX:
        lims.append(
            f"{n_total - _DASHBOARD_MAX} lower-rank themes elided (Strength × Confidence)"
        )
    return lims


__all__ = ["ThemeMonitor"]
