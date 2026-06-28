"""Phase 95-12 — Credit domain specialist analyst (narrative-only).

EXPLAINS the Credit Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.credit_domain_analyst.agent import CreditDomainAnalyst

__all__ = ["CreditDomainAnalyst"]
