"""Phase 95-12 — Financial Conditions domain specialist analyst (narrative-only).

EXPLAINS the Financial Conditions Domain; NEVER recomputes the Domain.health_score.
Returns the canonical SpecialistResponse contract (Phase 94 §M).
"""

from agents.financial_conditions_domain_analyst.agent import FinancialConditionsDomainAnalyst

__all__ = ["FinancialConditionsDomainAnalyst"]
