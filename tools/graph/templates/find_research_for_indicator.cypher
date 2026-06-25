// Phase 92 Plan 4 — find_research_for_indicator
//
// Given an EconomicIndicator id, return ResearchDocuments that discuss it
// together with the assets each document AFFECTS_ASSET-edges through.
//
// Parameters:
//   $indicator_id : str — FRED series id (e.g. 'CPIAUCSL')
//   $limit        : int — max rows
//
// Performance: relies on the unique constraints + indexes declared in
// ``knowledge/graph/migrations/0001_phase92_research_schema.cypher``
// (specifically research_document_published_at + economic_indicator_id /
// asset_id uniqueness for hash-join nodes). p95 ≤ 200 ms on the 50-doc
// fixture (REQ-92-5).

MATCH (i:EconomicIndicator {id: $indicator_id})<-[d:DISCUSSES_INDICATOR]-(rd:ResearchDocument)
OPTIONAL MATCH (rd)-[a:AFFECTS_ASSET]->(ast:Asset)
RETURN rd.document_id AS doc_id,
       rd.title AS title,
       rd.tier AS tier,
       rd.published_at AS published_at,
       d.confidence AS indicator_confidence,
       d.linker_stage AS linker_stage,
       collect({asset_id: ast.id, confidence: a.confidence, direction: a.direction}) AS assets
ORDER BY rd.published_at DESC
LIMIT $limit
