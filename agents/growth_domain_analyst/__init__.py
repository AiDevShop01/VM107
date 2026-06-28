"""Phase 95-12 — Growth domain specialist analyst (narrative-only).

EXPLAINS the Growth Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.growth_domain_analyst.agent import GrowthDomainAnalyst

__all__ = ["GrowthDomainAnalyst"]
