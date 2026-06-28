"""Phase 95-12 — Housing domain specialist analyst (narrative-only).

EXPLAINS the Housing Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.housing_domain_analyst.agent import HousingDomainAnalyst

__all__ = ["HousingDomainAnalyst"]
