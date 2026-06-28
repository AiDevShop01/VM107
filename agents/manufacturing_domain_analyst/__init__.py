"""Phase 95-12 — Manufacturing domain specialist analyst (narrative-only).

EXPLAINS the Manufacturing Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.manufacturing_domain_analyst.agent import ManufacturingDomainAnalyst

__all__ = ["ManufacturingDomainAnalyst"]
