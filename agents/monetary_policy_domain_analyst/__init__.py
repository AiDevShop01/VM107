"""Phase 95-12 — Monetary Policy domain specialist analyst (narrative-only).

EXPLAINS the Monetary Policy Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.monetary_policy_domain_analyst.agent import MonetaryPolicyDomainAnalyst

__all__ = ["MonetaryPolicyDomainAnalyst"]
