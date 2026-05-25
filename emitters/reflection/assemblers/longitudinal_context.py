"""Stage 4: LongitudinalContextAssembler — Phase 67 Plan 07 (REQ-67-4).

Pulls Phase 62 BehavioralEvolutionAsset + AdaptiveRecommendationAsset via
the VM100 chokepoint. These are the "where am I trending?" + "what is
the system suggesting I change?" inputs that let the synthesizer mix
immediate-session prompts with longitudinal prompts (coherence pass
temporal-mix requirement).

VM100 chokepoint methods:
    vm100_client.get_behavioral_evolution(account_id)
    → dict with keys: evolution_trend, behavioral_trajectory
    vm100_client.get_adaptive_recommendation(account_id)
    → dict with keys: recommendation, target_surface

CTX-DEC-2 (Phase 62 invariant): Behavioral metrics describe BEHAVIOR,
never psychology. No fearfulness_score / discipline_index / confidence
labels are read from these payloads.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from emitters.reflection.assemblers.pattern_context import PatternContext

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LongitudinalContext:
    """Phase 62 evolution + adaptive recommendation snapshot.

    A single LongitudinalContext per account+session (not per-pattern) —
    the synthesizer attaches it as broad cross-prompt evidence.
    """

    evolution_trend: str = ""
    adaptive_recommendation: str = ""
    behavioral_trajectory: str = ""


class LongitudinalContextAssembler:
    """Stage 4: Phase 62 evolution + adaptive recommendation."""

    def __init__(self, vm100_client: Any | None = None) -> None:
        self._vm100 = vm100_client
        self.missing_sources: set[str] = set()

    def assemble(
        self,
        account_id: int,
        session_date: date,
        patterns: list[PatternContext],
    ) -> list[LongitudinalContext]:
        """Return list[LongitudinalContext] — at most one entry.

        Empty list when BOTH evolution + adaptive recommendation are
        unavailable (signals to the synthesizer that no longitudinal
        layer can support eligibility for longitudinal-temporal prompts).
        """
        if self._vm100 is None:
            return []

        evolution: dict[str, Any] = {}
        adaptive: dict[str, Any] = {}

        try:
            evolution = self._vm100.get_behavioral_evolution(account_id) or {}
        except Exception as exc:
            log.warning(
                "behavioral_evolution_unavailable: %s(%s)",
                type(exc).__name__,
                exc,
            )
            self.missing_sources.add("behavioral_evolution")

        try:
            adaptive = self._vm100.get_adaptive_recommendation(account_id) or {}
        except Exception as exc:
            log.warning(
                "adaptive_recommendation_unavailable: %s(%s)",
                type(exc).__name__,
                exc,
            )
            self.missing_sources.add("adaptive_recommendation")

        if not evolution and not adaptive:
            # Nothing to layer in — return empty so the synthesizer can
            # disqualify longitudinal-temporal eligibility cleanly.
            return []

        return [
            LongitudinalContext(
                evolution_trend=str(evolution.get("evolution_trend") or ""),
                adaptive_recommendation=str(adaptive.get("recommendation") or ""),
                behavioral_trajectory=str(evolution.get("behavioral_trajectory") or ""),
            )
        ]
