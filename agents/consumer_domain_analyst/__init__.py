"""Phase 95-12 — Consumer domain specialist analyst (narrative-only).

EXPLAINS the Consumer Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.consumer_domain_analyst.agent import ConsumerDomainAnalyst

__all__ = ["ConsumerDomainAnalyst"]
