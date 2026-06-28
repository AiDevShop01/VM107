"""Phase 95-12 — Inflation domain specialist analyst (narrative-only).

EXPLAINS the Inflation Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.inflation_domain_analyst.agent import InflationDomainAnalyst

__all__ = ["InflationDomainAnalyst"]
