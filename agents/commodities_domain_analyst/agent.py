"""Phase 169 Plan 06 — CommoditiesDomainAnalyst (config-only subclass of DomainAgent).

Shrunk from the legacy 143-line near-verbatim copy to a config-only subclass of the
generic :class:`DomainAgent` base (``core/agents/domain_agent.py``, Plan 169-02). The
base supplies BOTH the legacy ``invoke(Domain) -> SpecialistResponse`` narrative surface
and the net-new deterministic ``assess(pack) -> DomainAssessment`` path (AGV-09/AGV-10);
the per-domain knowledge comes from this manifest's ``domain_definition:`` block
(``registry/agent_profile/vm107.commodities_domain_analyst.yaml``, Plan 169-05).

Only the per-slug identity (``DOMAIN`` / ``DOMAIN_SLUG`` / ``AGENT_ID``) stays on the
concrete class — kept here so the per-slug static guard ``test_never_recomputes_score``
reads a real file. The base lives OUTSIDE the grepped path; its own ban is closed by
``test_domain_base_engine_lock``. LLM-FREE — no engine/LLM import (Phase 94 §F.3 +
LD-90-1). D-06: the pre-migration copy is retained as ``agent.py.bak`` (reversible floor).
"""

from __future__ import annotations

from core.agents.domain_agent import DomainAgent


class CommoditiesDomainAnalyst(DomainAgent):
    """Config-only specialist analyst for the Commodities domain."""

    DOMAIN = "Commodities"
    DOMAIN_SLUG = "commodities"
    AGENT_ID = "vm107.commodities_domain_analyst"


__all__ = ["CommoditiesDomainAnalyst"]
