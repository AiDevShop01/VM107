"""Phase 94-05 — InflationAnalyst specialist (narrative-only).

EXPLAINS the Inflation Pillar; NEVER recomputes the score. Returns
canonical :class:`SpecialistResponse` per §M.
"""

from __future__ import annotations

from contracts.economic_intelligence.pillars import Pillar
from contracts.economic_intelligence.specialist_response import SpecialistResponse


class InflationAnalyst:
    """Specialist analyst for the Inflation pillar."""

    DOMAIN = "Inflation"
    AGENT_ID = "vm107.inflation_analyst"

    def invoke(
        self, pillar: Pillar, context: dict | None = None
    ) -> SpecialistResponse:
        assert pillar.name == "Inflation", (
            f"InflationAnalyst received {pillar.name} pillar — expected Inflation"
        )

        narrative = self._compose_narrative(pillar)
        citations = list(pillar.contributors[:5])
        evidence = [
            {"indicator_id": cid, "role": "contributor"}
            for cid in pillar.contributors
        ]
        limitations = self._derive_limitations(pillar)
        related = self._related_entities(pillar)

        return SpecialistResponse(
            answer=narrative,
            confidence=pillar.confidence,
            citations=citations,
            evidence=evidence,
            limitations=limitations,
            related_entities=related,
        )

    def _compose_narrative(self, pillar: Pillar) -> str:
        top = pillar.contributors[:3]
        m = pillar.momentum
        return (
            f"Inflation pressure is at {pillar.level:.0f}/100 with state {pillar.state.value}. "
            f"Momentum on the 1m horizon is {m['1m']:+.2f}, 3m {m['3m']:+.2f}, and "
            f"12m {m['12m']:+.2f}. Breadth across the inflation basket is "
            f"{pillar.breadth * 100:.0f}%. Top contributing series: {', '.join(top)}. "
            f"Pay attention to whether the heat is concentrated in goods, services, or "
            f"shelter — those subgroups react differently to monetary tightening and "
            f"matter for the next FOMC decision."
        )

    def _derive_limitations(self, pillar: Pillar) -> list[str]:
        lims: list[str] = []
        if pillar.confidence < 0.5:
            lims.append("upstream confidence degraded — interpret cautiously")
        if pillar.breadth < 0.4:
            lims.append("narrow basket participation — signal driven by few series")
        return lims

    def _related_entities(self, pillar: Pillar) -> list[str]:
        related = [
            f"pillar:{pillar.name}",
            "domain:inflation",
        ]
        related.extend(f"indicator:{cid}" for cid in pillar.contributors[:3])
        return related


__all__ = ["InflationAnalyst"]
