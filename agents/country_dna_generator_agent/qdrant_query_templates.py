"""Structural query templates for the country_dna_generator agent (Plan 96-05).

Each template represents a candidate DNA tag. The hybrid pipeline:

1. Qdrant retrieval — the agent runs ``query`` against the country_profiles
   collection (filtered by ``section`` + the target country's iso); the top
   hit must score >= ``min_score`` to be a candidate.
2. Neo4j confirmation — the agent walks the relationship graph via
   ``graph_predicate`` (declarative, applied by ``_predicate_fns`` in
   ``agent.py``) and counts confirming paths.
3. Emit — if both stages pass, a ``EconomicDnaTag`` ships with
   provenance_sections (top-3 Qdrant section IDs) +
   provenance_graph_paths (top-3 Cypher signatures).

Phase 94-07 baseline preserved: ``reserve-currency-issuer``,
``services-led``, and ``consumer-driven`` are all here so the US payload
floor stays intact while the rest of the catalogue differentiates by
country (commodity exporters, oil-dependent, financial hubs, etc.).
"""

from __future__ import annotations

from typing import Any

# Each template carries a graph_predicate STRING. The agent's _confirms_tag()
# method dispatches on this string via a small predicate table. We keep the
# predicates declarative (strings) rather than callables so the templates
# remain serializable and the agent can be introspected by lookup_capability.

STRUCTURAL_QUERY_TEMPLATES: list[dict[str, Any]] = [
    {
        "tag_id": "reserve-currency-issuer",
        "label": "Reserve currency issuer",
        "query": "country issues a reserve currency held in global FX reserves",
        "section": "ECONOMY",
        "min_score": 0.65,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.70,
    },
    {
        "tag_id": "commodity-exporter",
        "label": "Commodity exporter",
        "query": "country's export basket dominated by raw commodities",
        "section": "ECONOMY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.65,
    },
    {
        "tag_id": "services-led",
        "label": "Services-led economy",
        "query": "country GDP majority from services sector",
        "section": "ECONOMY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.65,
    },
    {
        "tag_id": "manufacturing-led",
        "label": "Manufacturing-led economy",
        "query": "country GDP majority from manufacturing and industrial production",
        "section": "ECONOMY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
    {
        "tag_id": "oil-export-dependent",
        "label": "Oil-export dependent",
        "query": "country economic activity highly dependent on petroleum exports",
        "section": "ENERGY",
        "min_score": 0.70,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.70,
    },
    {
        "tag_id": "high-debt-economy",
        "label": "High public debt",
        "query": "country with public debt-to-GDP exceeding 80 percent",
        "section": "ECONOMY",
        "min_score": 0.55,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.55,
    },
    {
        "tag_id": "consumer-driven",
        "label": "Consumer-driven demand",
        "query": "household consumption majority of GDP demand-side composition",
        "section": "ECONOMY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
    {
        "tag_id": "export-driven",
        "label": "Export-driven economy",
        "query": "country exports as percentage of GDP exceeding 40 percent",
        "section": "ECONOMY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.55,
    },
    {
        "tag_id": "financial-sector-hub",
        "label": "Financial sector hub",
        "query": "country economy heavily oriented to international banking and finance",
        "section": "ECONOMY",
        "min_score": 0.65,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.65,
    },
    {
        "tag_id": "demographic-headwind",
        "label": "Aging demographic headwind",
        "query": "country with shrinking working-age population and aging society",
        "section": "PEOPLE",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
    {
        "tag_id": "young-demographic-dividend",
        "label": "Young demographic dividend",
        "query": "country with majority young working-age population and growing labor force",
        "section": "PEOPLE",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
    {
        "tag_id": "energy-importer",
        "label": "Net energy importer",
        "query": "country imports majority of its energy consumption needs",
        "section": "ENERGY",
        "min_score": 0.60,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
    {
        "tag_id": "central-bank-independent",
        "label": "Independent central bank",
        "query": "country has politically independent central bank with explicit inflation mandate",
        "section": "GOVERNMENT",
        "min_score": 0.55,
        "graph_predicate": "any_outgoing",
        "baseline_confidence": 0.60,
    },
]


__all__ = ["STRUCTURAL_QUERY_TEMPLATES"]
