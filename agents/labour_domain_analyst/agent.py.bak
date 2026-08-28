"""Phase 95-12 — LabourDomainAnalyst specialist (narrative-only).

EXPLAINS the Labour Domain (one of the 12 canonical macro domains —
CONTEXT §A) in natural language; NEVER recomputes the
``Domain.health_score`` (LLM-FREE engine lock per Phase 94 §F.3 + LD-90-1).
Returns the canonical :class:`SpecialistResponse` per Phase 94 §M.

The template-based narrative is intentionally deterministic for this wave
so the loop closes end-to-end without an LLM round-trip. A later wave can
swap in an LLM completion for richer prose — the contract surface
(SpecialistResponse) is the immutable boundary.

Mirrors :class:`agents.growth_analyst.agent.GrowthAnalyst` shape exactly
(Pattern 3 — verbatim mirror). The static guard
``test_never_recomputes_score`` enforces the engine-import ban.
"""

from __future__ import annotations

from contracts.economic_intelligence.domain import Domain
from contracts.economic_intelligence.specialist_response import SpecialistResponse


_TOP_INDICATOR_COUNT = 5
_TOP_DRIVER_COUNT = 3


class LabourDomainAnalyst:
    """Specialist analyst for the Labour Domain."""

    DOMAIN = "Labour"
    DOMAIN_SLUG = "labour"
    AGENT_ID = "vm107.labour_domain_analyst"

    def invoke(
        self, domain: Domain, context: dict | None = None
    ) -> SpecialistResponse:
        assert domain.slug == self.DOMAIN_SLUG, (
            f"LabourDomainAnalyst received domain.slug={domain.slug!r} — "
            f"expected {self.DOMAIN_SLUG!r}"
        )

        narrative = self._compose_narrative(domain)
        citations = [
            ind.indicator_id for ind in domain.top_indicators[:_TOP_INDICATOR_COUNT]
        ]
        evidence = [
            {
                "driver": d.name,
                "direction": d.direction,
                "contribution": d.contribution,
            }
            for d in domain.drivers
        ]
        limitations = self._derive_limitations(domain)
        related = self._related_entities(domain)

        return SpecialistResponse(
            answer=narrative,
            confidence=domain.confidence,
            citations=citations,
            evidence=evidence,
            limitations=limitations,
            related_entities=related,
        )

    # --------------------------------------------------------- internals
    def _compose_narrative(self, domain: Domain) -> str:
        """Build a 60-90 word headline from Domain payload.

        Deterministic template — domain-specific colour comes from the
        Domain payload data, not from per-agent code. The 60-90 word window
        is enforced by ``test_headline_length_60_to_90_words``.
        """
        top_drivers = domain.drivers[:_TOP_DRIVER_COUNT]
        top_indicators = domain.top_indicators[:_TOP_DRIVER_COUNT]

        driver_phrase = (
            ", ".join(
                f"{d.name} ({d.direction}, contribution {d.contribution:+.2f})"
                for d in top_drivers
            )
            if top_drivers
            else "no individual drivers stand out at the moment"
        )
        indicator_phrase = (
            ", ".join(ind.title for ind in top_indicators)
            if top_indicators
            else "no primary indicators currently published"
        )
        tailwind_phrase = (
            f"Tailwinds: {'; '.join(domain.tailwinds[:2])}."
            if domain.tailwinds
            else "Tailwinds are limited."
        )
        headwind_phrase = (
            f"Headwinds: {'; '.join(domain.headwinds[:2])}."
            if domain.headwinds
            else "Headwinds are limited."
        )

        return (
            f"The {self.DOMAIN} domain is currently {domain.current_state} "
            f"with a health score of {domain.health_score:.0f}/100 and a "
            f"trend reading of {domain.trend_score:+.0f}, against a breadth "
            f"of {domain.breadth_score:.0f}/100; risk level reads as "
            f"{domain.risk_level} at confidence {domain.confidence:.2f}. "
            f"Top drivers behind the print: {driver_phrase}. Primary "
            f"indicators powering the read: {indicator_phrase}. "
            f"{tailwind_phrase} {headwind_phrase} The state reading reflects "
            f"the joint signal from level, momentum, and breadth; specialists "
            f"should drill into individual contributors for the driver story."
        )

    def _derive_limitations(self, domain: Domain) -> list[str]:
        lims: list[str] = []
        if domain.confidence < 0.5:
            lims.append(
                f"upstream confidence degraded ({domain.confidence:.2f}) "
                f"— interpret cautiously"
            )
        if not domain.drivers:
            lims.append("no drivers available")
        if domain.breadth_score < 40.0:
            lims.append(
                "narrow basket participation — signal driven by few series"
            )
        if domain.status.value != "READY":
            lims.append(f"section status: {domain.status.value}")
        return lims

    def _related_entities(self, domain: Domain) -> list[str]:
        related: list[str] = [
            f"domain:{domain.slug}",
        ]
        for pillar in domain.primary_pillars:
            related.append(f"pillar:{pillar}")
        for ind in domain.top_indicators[:_TOP_DRIVER_COUNT]:
            related.append(f"indicator:{ind.indicator_id}")
        return related


__all__ = ["LabourDomainAnalyst"]
