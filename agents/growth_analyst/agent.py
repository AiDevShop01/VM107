"""Phase 94-05 — GrowthAnalyst specialist (narrative-only).

EXPLAINS the Growth Pillar in natural language; NEVER recomputes the
score. Returns the canonical :class:`SpecialistResponse` per §M.

The template-based narrative is intentionally deterministic for Wave 3a
so the loop closes end-to-end without an LLM round-trip. 94-06 can swap
in an LLM completion for richer prose — the contract surface
(SpecialistResponse) is the immutable boundary.

§F + §J lock — "AI explains, never calculates". Test
``test_never_recomputes_score`` enforces the static guard.
"""

from __future__ import annotations

from contracts.economic_intelligence.pillars import Pillar
from contracts.economic_intelligence.specialist_response import SpecialistResponse


_TOP_CONTRIBUTOR_COUNT = 3


class GrowthAnalyst:
    """Specialist analyst for the Growth pillar."""

    DOMAIN = "Growth"
    AGENT_ID = "vm107.growth_analyst"

    def invoke(
        self, pillar: Pillar, context: dict | None = None
    ) -> SpecialistResponse:
        assert pillar.name == "Growth", (
            f"GrowthAnalyst received {pillar.name} pillar — expected Growth"
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

    # --------------------------------------------------------- internals
    def _compose_narrative(self, pillar: Pillar) -> str:
        top = pillar.contributors[:_TOP_CONTRIBUTOR_COUNT]
        m = pillar.momentum
        return (
            f"Growth is at {pillar.level:.0f}/100 with state {pillar.state.value}. "
            f"Short-term momentum (1m) is {m['1m']:+.2f}, medium-term (3m) {m['3m']:+.2f}, "
            f"and long-term (12m) {m['12m']:+.2f}. "
            f"Breadth across the basket is {pillar.breadth * 100:.0f}%, suggesting "
            f"{'broad-based' if pillar.breadth > 0.6 else 'narrow'} participation. "
            f"Primary contributing indicators: {', '.join(top)}. "
            f"The state reading reflects the joint signal from level and momentum; "
            f"specialists should drill into individual contributors for the driver story."
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
            "domain:growth",
        ]
        related.extend(f"indicator:{cid}" for cid in pillar.contributors[:3])
        return related


__all__ = ["GrowthAnalyst"]
