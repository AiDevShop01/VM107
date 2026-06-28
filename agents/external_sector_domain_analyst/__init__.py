"""Phase 95-12 — External Sector domain specialist analyst (narrative-only).

EXPLAINS the External Sector Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.external_sector_domain_analyst.agent import ExternalSectorDomainAnalyst

__all__ = ["ExternalSectorDomainAnalyst"]
