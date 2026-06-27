"""Phase 94-05 — RiskAnalyst specialist (narrative-only).

EXPLAINS the RiskAppetite Pillar; NEVER recomputes the score. Returns
canonical :class:`SpecialistResponse` per §M.
"""

from __future__ import annotations

from contracts.economic_intelligence.pillars import Pillar
from contracts.economic_intelligence.specialist_response import SpecialistResponse


class RiskAnalyst:
    """Specialist analyst for the RiskAppetite pillar."""

    DOMAIN = "RiskAppetite"
    AGENT_ID = "vm107.risk_analyst"

    def invoke(
        self, pillar: Pillar, context: dict | None = None
    ) -> SpecialistResponse:
        assert pillar.name == "RiskAppetite", (
            f"RiskAnalyst received {pillar.name} pillar — expected RiskAppetite"
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
            f"Risk appetite is at {pillar.level:.0f}/100 with state {pillar.state.value}. "
            f"Momentum: 1m {m['1m']:+.2f}, 3m {m['3m']:+.2f}, 12m {m['12m']:+.2f}. "
            f"Breadth is {pillar.breadth * 100:.0f}% of the cross-asset risk basket. "
            f"Watch the spread/vol pair: {', '.join(top)}. Risk appetite typically leads "
            f"growth by 4-8 weeks at major turning points; deterioration here with stable "
            f"growth often signals an imminent regime change worth flagging to portfolio risk."
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
            "domain:risk_appetite",
        ]
        related.extend(f"indicator:{cid}" for cid in pillar.contributors[:3])
        return related


__all__ = ["RiskAnalyst"]
