"""Phase 95-12 — Labour domain specialist analyst (narrative-only).

EXPLAINS the Labour Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.labour_domain_analyst.agent import LabourDomainAnalyst

__all__ = ["LabourDomainAnalyst"]
