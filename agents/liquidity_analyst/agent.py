"""Phase 94-05 — LiquidityAnalyst specialist (narrative-only).

EXPLAINS the Liquidity Pillar; NEVER recomputes the score. Returns
canonical :class:`SpecialistResponse` per §M.
"""

from __future__ import annotations

from contracts.economic_intelligence.pillars import Pillar
from contracts.economic_intelligence.specialist_response import SpecialistResponse


class LiquidityAnalyst:
    """Specialist analyst for the Liquidity pillar."""

    DOMAIN = "Liquidity"
    AGENT_ID = "vm107.liquidity_analyst"

    def invoke(
        self, pillar: Pillar, context: dict | None = None
    ) -> SpecialistResponse:
        assert pillar.name == "Liquidity", (
            f"LiquidityAnalyst received {pillar.name} pillar — expected Liquidity"
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
            f"Liquidity is at {pillar.level:.0f}/100 with state {pillar.state.value}. "
            f"Short-term momentum (1m) is {m['1m']:+.2f}, medium-term (3m) {m['3m']:+.2f}, "
            f"and long-term (12m) {m['12m']:+.2f}. Breadth is {pillar.breadth * 100:.0f}%. "
            f"Primary signals: {', '.join(top)}. Bank reserves, RRP take-up, and the "
            f"shape of the yield curve are the canonical reads on USD liquidity; central "
            f"bank balance-sheet flow and Treasury issuance are the upstream drivers worth "
            f"watching for the next regime transition."
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
            "domain:liquidity",
        ]
        related.extend(f"indicator:{cid}" for cid in pillar.contributors[:3])
        return related


__all__ = ["LiquidityAnalyst"]
