"""Phase 168 Plan 06 Task 2 — Evidence retrieval-ranking facet (ENRICHMENT, G10).

Retrieves the most relevant PRIOR ASSESSMENTS for the domain over Qdrant
(192.168.1.151:6333) and ranks them, populating the ``prior_assessment`` facet
slot (the "prior DomainAssessment attached for continuity" — evidence-driven,
D-01) from the top-ranked hit.

HITS-FIRST (AGV-07 + project memory ``feedback_health_bus_reads_must_be_hits_first``,
catalogue 07 §6d): compute the hits FIRST; the ``SourceHealthRegistry`` DEGRADED
status is consulted ONLY ``if not hits`` — real results are NEVER discarded as
degraded because the bus reports the source down. A bus-first read would mask real
hits (the recurring project defect this facet must not reintroduce).

Tier discipline (D-07): Evidence ranking is ENRICHMENT — on no hits / Qdrant down /
no reader it OMITS the facet with a reason (non-downgrading), never raises (D-02).

G10: Qdrant is reached ONLY through the injected typed ``evidence_reader`` seam —
never a raw store. The concrete Qdrant-backed reader adapter is a 169 dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fingpt_core.contracts.evidence_pack import FacetIntegrity, PriorAssessmentFacet

from core.evidence import tiers
from core.evidence.facets import is_latest_only_lookahead, parse_dt, to_iso

# Look-ahead honesty (Constitution 18): the evidence retrieval is latest-only, so
# a run whose knowledge_time is materially in the past served a look-ahead —
# flagged on the outcome reason (contribution.py's is_latest_only_flagged shape).
_LATEST_ONLY_REASON = (
    "is_latest_only_flagged: latest-only evidence retrieval served a past as-of "
    "(look-ahead honesty — Constitution 18)"
)

# The source_id the Evidence facet registers under in the SourceHealthRegistry —
# consulted hits-first (only when a retrieval returned no hits).
EVIDENCE_SOURCE_ID: str = "qdrant.evidence"

# Bounded retrieval fan-out; the top-ranked hit populates prior_assessment.
DEFAULT_LIMIT: int = 5


def _normalize_hits(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict) and "hits" in raw:
        raw = raw.get("hits") or []
    return [h for h in raw if isinstance(h, dict)]


def _rank_key(hit: dict):
    """Deterministic ranking: score desc, assessment_id asc as a stable tiebreak."""
    try:
        score = float(hit.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return (-score, str(hit.get("assessment_id") or ""))


def _to_prior_assessment(hit: dict) -> PriorAssessmentFacet:
    kt = hit.get("knowledge_time")
    kt_dt = kt if isinstance(kt, datetime) else parse_dt(kt)
    return PriorAssessmentFacet(
        assessment_id=str(hit["assessment_id"]) if hit.get("assessment_id") is not None else None,
        outcome=str(hit["outcome"]) if hit.get("outcome") is not None else None,
        knowledge_time=kt_dt,
    )


def _source_is_degraded(source_health: Any) -> bool:
    """True when the SourceHealthRegistry reports the Evidence/Qdrant source down.

    Consulted ONLY when a retrieval returned no hits (hits-first). Defensive: an
    unknown/absent source is NOT treated as degraded (honest — we cannot claim an
    outage we did not observe).
    """
    if source_health is None:
        return False
    try:
        snapshot = source_health.snapshot()
    except Exception:  # noqa: BLE001 - never let a health read raise into the facet
        return False
    record = snapshot.get(EVIDENCE_SOURCE_ID)
    if record is None:
        return False
    return getattr(record, "available", True) is False


def compose_evidence_ranking(ctx) -> tiers.FacetOutcome:
    reader = getattr(ctx.deps, "evidence_reader", None)
    if reader is None:
        return tiers.FacetOutcome(
            name="prior_assessment",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no evidence_reader configured (Qdrant retrieval seam; 169 wiring)",
        )

    req = ctx.request
    limit = getattr(ctx.deps, "evidence_limit", None) or DEFAULT_LIMIT
    # Forward the run's as-of to the retrieval seam (GAP 3): a hardcoded None was a
    # silent look-ahead. Hits-first discipline below is unchanged.
    raw = reader.search(
        req.country, req.domain_slug, knowledge_time=to_iso(req.knowledge_time), limit=limit
    )
    hits = _normalize_hits(raw)

    # HITS-FIRST: only consult the health bus when NO real results came back — a
    # DEGRADED bus signal must never discard real hits (AGV-07).
    if not hits:
        source_health = getattr(ctx.deps, "source_health", None)
        if _source_is_degraded(source_health):
            return tiers.FacetOutcome(
                name="prior_assessment",
                ok=False,
                integrity=FacetIntegrity.UNAVAILABLE,
                reason=f"evidence retrieval returned no hits and {EVIDENCE_SOURCE_ID} is degraded",
            )
        return tiers.FacetOutcome(
            name="prior_assessment",
            ok=False,
            integrity=FacetIntegrity.NEUTRAL,
            reason="no relevant prior assessment found (evidence retrieval returned no hits)",
        )

    top = sorted(hits, key=_rank_key)[0]
    reason = _LATEST_ONLY_REASON if is_latest_only_lookahead(req.knowledge_time, latest_only=True) else None
    return tiers.FacetOutcome(
        name="prior_assessment",
        ok=True,
        integrity=FacetIntegrity.NEUTRAL,
        reason=reason,
        value=_to_prior_assessment(top),
    )
