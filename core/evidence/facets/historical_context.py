"""Phase 168 Plan 06 Task 2 — HistoricalContext facet composer (ENRICHMENT, G10).

Two sub-paths (D-01):

  * PERCENTILE (always-available) — reads where the current domain read sits in
    its own history through the typed VM102 ``percentile_reader`` seam
    (``analytics/distribution.py::percentile_of_latest`` behind it) and populates
    the ``HistoricalPercentileFacet``. This is the sub-path that SERVES the facet.
  * ANALOGUE (best-effort) — retrieves historical analogue releases from the
    VM105 Neo4j macro graph via ``counterfactual.analogue_retrieval.query_analogues``.
    Attempted ONLY when ``VM105_NEO4J_URL`` is set (env-driven, no fallback per
    project lock). Any failure — env unset, ``NotImplementedError``, or a
    connection error — is CAUGHT here and the analogue sub-facet is omitted with a
    recorded reason; it NEVER propagates (D-02). The percentile still serves.

Tier discipline (D-07): HistoricalContext is ENRICHMENT — when it cannot serve
(no percentile reader / no data) it OMITS with a reason (non-downgrading), never
raises. The analogue-count / omit-reason is recorded on the outcome reason so the
manifest is honest about which sub-paths contributed (07 §6a).

G10: the percentile is reached ONLY through the injected typed ``percentile_reader``
seam — never a raw store / ``compute_domain`` / a series.
"""

from __future__ import annotations

import os
from typing import Any

from fingpt_core.contracts.evidence_pack import FacetIntegrity, HistoricalPercentileFacet

from core.evidence import tiers
from core.evidence.facets import bounded, is_latest_only_lookahead, to_iso

# Look-ahead honesty (Constitution 18): the percentile read is latest-only, so a
# run whose knowledge_time is materially in the past served a look-ahead — flagged
# on the outcome reason (mirroring contribution.py's is_latest_only_flagged shape).
_LATEST_ONLY_REASON = (
    "is_latest_only_flagged: latest-only historical-percentile read served a past "
    "as-of (look-ahead honesty — Constitution 18)"
)


def _percentile_facet(read: dict) -> HistoricalPercentileFacet | None:
    """Map a typed percentile read onto the facet; ``None`` when no percentile."""
    pct = bounded(read.get("percentile"), 0.0, 100.0)
    if pct is None:
        return None
    window = read.get("window")
    return HistoricalPercentileFacet(
        percentile=pct,
        window=str(window) if window is not None else None,
        integrity=FacetIntegrity.NEUTRAL,
    )


def _analogue_reason(read: dict) -> str:
    """Attempt the analogue sub-path; return an honest status reason (never raise).

    Gated on VM105_NEO4J_URL (no fallback). Any error omits the analogue sub-facet
    with a reason — the NotImplementedError / connection error never propagates.
    """
    if not os.environ.get("VM105_NEO4J_URL"):
        return "analogue sub-facet omitted: VM105_NEO4J_URL unset (percentile sub-path serves)"

    surprise = read.get("surprise")
    indicator = read.get("indicator")
    if surprise is None or indicator is None:
        return "analogue sub-facet omitted: no indicator/surprise input for analogue retrieval"

    try:
        # Local import avoids a hard dependency on the counterfactual package at
        # module import time (the percentile sub-path must load standalone).
        from core.counterfactual.analogue_retrieval import query_analogues

        analogues = query_analogues(indicator=str(indicator), hypothetical_surprise=float(surprise))
        return f"analogue sub-facet: {len(analogues)} analogue(s) retrieved (VM105)"
    except Exception as exc:  # ENRICHMENT: omit the analogue path honestly.
        return f"analogue sub-facet omitted: {type(exc).__name__}: {exc}"


def compose_historical_context(ctx) -> tiers.FacetOutcome:
    reader = getattr(ctx.deps, "percentile_reader", None)
    if reader is None:
        return tiers.FacetOutcome(
            name="historical_context",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no percentile_reader configured (G10 typed seam; 169 wiring)",
        )

    req = ctx.request
    # Forward the run's as-of to the reader seam (GAP 3): a hardcoded None was a
    # silent look-ahead. The concrete reader is latest-only today, so we ALSO flag
    # a materially-past as-of on the outcome reason (never a silent point-in-time lie).
    read: Any = reader.historical_percentile(
        req.country, req.domain_slug, knowledge_time=to_iso(req.knowledge_time)
    )
    if not isinstance(read, dict):
        read = {} if read is None else dict(getattr(read, "__dict__", {}))

    facet = _percentile_facet(read) if read else None
    if facet is None:
        return tiers.FacetOutcome(
            name="historical_context",
            ok=False,
            integrity=FacetIntegrity.UNKNOWN,
            reason="no percentile available (historical context could not be established)",
        )

    # Percentile serves; the analogue sub-path is best-effort and recorded honestly.
    # Carry BOTH the analogue sub-path status AND the look-ahead flag on the reason.
    reason = _analogue_reason(read)
    if is_latest_only_lookahead(req.knowledge_time, latest_only=True):
        reason = f"{reason} | {_LATEST_ONLY_REASON}"
    return tiers.FacetOutcome(
        name="historical_context",
        ok=True,
        integrity=FacetIntegrity.NEUTRAL,
        reason=reason,
        value=facet,
    )
