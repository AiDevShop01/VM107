"""Phase 96 Plan 05 — Country DNA generator agent (REQ-96-4).

Hybrid Neo4j + Qdrant agent emitting 5-10 structural economic-DNA tags per
country with provenance (CountryProfileSection IDs + Cypher graph paths).

Registry: VM107/registry/agent_profile/vm107.country_dna_generator.yaml
  (impact_on_decision=MEDIUM — CONTEXT lock; least-privilege denied_tools).
Replaces Phase 94-07 `_DEFAULT_DNA_TAGS` heuristic at
VM100/backend/api/macro_situation/section_resolvers/country_card.py:64.
"""

from agents.country_dna_generator_agent.agent import CountryDnaGenerator

__all__ = ["CountryDnaGenerator"]
