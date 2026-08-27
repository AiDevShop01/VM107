"""Phase 168 Plan 05 Task 2 — Contribution facet composer (IMPORTANT, G10).

Reads the domain's top contributors through the typed contribution seam and maps
them onto the ``top_contributors`` tuple of ``ContributorFacet``. The underlying
``RegimeContributionEngine.contribution(...)`` is latest-only (its ``date`` as-of
param is reserved-but-ignored per RESEARCH), so when the run's ``knowledge_time``
is materially in the past the facet declares the look-ahead by recording
``is_latest_only_flagged`` in its manifest reason (Constitution 18) — never a
silent point-in-time lie.

Contribution is IMPORTANT: a failed read degrades the pack to ``partial`` with a
warning, never a raise. G10: data is reached ONLY through the injected typed
``contribution_reader`` seam — never a raw store / direct compute call.
"""

from __future__ import annotations

from typing import Any, Iterable

from fingpt_core.contracts.evidence_pack import ContributorFacet, FacetIntegrity

from core.evidence import tiers
from core.evidence.facets import bounded, is_latest_only_lookahead, to_iso

_LATEST_ONLY_REASON = (
    "is_latest_only_flagged: latest-only contribution read served a past as-of "
    "(look-ahead honesty — Constitution 18)"
)


def _to_contributors(raw: Any) -> tuple[ContributorFacet, ...]:
    """Map a contribution result (iterable of rows / a struct) to typed facets."""
    rows: Iterable
    if raw is None:
        return ()
    if isinstance(raw, dict) and "top_contributors" in raw:
        rows = raw.get("top_contributors") or []
    elif isinstance(raw, dict):
        # a {name: contribution} mapping
        rows = [{"name": k, "contribution": v} for k, v in raw.items()]
    else:
        rows = raw  # assume already an iterable of rows

    out: list[ContributorFacet] = []
    for row in rows:
        if isinstance(row, ContributorFacet):
            out.append(row)
            continue
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("indicator") or row.get("id")
        contribution = bounded(row.get("contribution", row.get("weight")), -1.0, 1.0)
        if name is None or contribution is None:
            continue
        out.append(
            ContributorFacet(
                name=str(name),
                contribution=contribution,
                confidence=bounded(row.get("confidence"), 0.0, 1.0),
            )
        )
    return tuple(out)


def compose_contribution(ctx) -> tiers.FacetOutcome:
    reader = getattr(ctx.deps, "contribution_reader", None)
    if reader is None:
        return tiers.FacetOutcome(
            name="contribution",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no contribution_reader configured (G10 typed seam)",
        )

    req = ctx.request
    result = reader.contribution(req.country, req.domain_slug, knowledge_time=to_iso(req.knowledge_time))
    contributors = _to_contributors(result)
    if not contributors:
        return tiers.FacetOutcome(
            name="contribution",
            ok=False,
            integrity=FacetIntegrity.UNKNOWN,
            reason="contribution read returned no contributors",
        )

    # Latest-only look-ahead honesty: contribution() ignores its reserved date
    # param, so a materially-past as-of is flagged in the manifest.
    reason = _LATEST_ONLY_REASON if is_latest_only_lookahead(req.knowledge_time, latest_only=True) else None
    return tiers.FacetOutcome(
        name="contribution",
        ok=True,
        integrity=FacetIntegrity.NEUTRAL,
        reason=reason,
        value=contributors,
    )
