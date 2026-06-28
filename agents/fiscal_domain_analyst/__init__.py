"""Phase 95-12 — Fiscal domain specialist analyst (narrative-only).

EXPLAINS the Fiscal Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.fiscal_domain_analyst.agent import FiscalDomainAnalyst

__all__ = ["FiscalDomainAnalyst"]
