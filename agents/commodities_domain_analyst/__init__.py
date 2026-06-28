"""Phase 95-12 — Commodities domain specialist analyst (narrative-only).

EXPLAINS the Commodities Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.commodities_domain_analyst.agent import CommoditiesDomainAnalyst

__all__ = ["CommoditiesDomainAnalyst"]
