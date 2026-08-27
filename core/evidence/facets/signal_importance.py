"""Phase 168 Plan 06 Task 1 — SignalImportance facet composer (IMPORTANT, G10).

NET-NEW compute (D-01, PATTERNS No-Analog-Found): ranks the domain's candidate
signals into a bounded ``top_k`` AND an ``excluded`` set (each excluded signal
carrying a reason) and returns a FROZEN STRUCT — never a series (mirrors
``distribution.py`` scalar-return + the ``RegimeContribution`` struct shape). The
assembler maps the struct onto ``top_signals`` / ``excluded_signals`` (D-03).

Tier discipline (D-07): SignalImportance is IMPORTANT. If the concrete typed
reader seam is not wired yet (169), the facet is recorded as a DEFERRED omission
(non-downgrading) — the compute landed in 168-06, the concrete VM102
quant/correlation-lead-lag reader adapter is a 169 dependency (mirrors 168-03's
``QuantReader`` seam + 168-05's deferred-not-failed decision). When the seam IS
present but the read fails/returns nothing, the facet degrades the pack to
``partial`` with a warning — it NEVER raises (D-02).

G10: candidate signals are reached ONLY through the injected typed
``signal_reader`` seam — never a raw store, never ``compute_domain``. The reader
returns scalar/struct rows (``signal_id`` + ``importance`` + optional
``eligible`` / ``exclude_reason``), never a series.
"""

from __future__ import annotations

from typing import Any, Iterable

from fingpt_core.contracts.evidence_pack import FacetIntegrity, SignalFacet

from core.evidence import tiers
from core.evidence.facets import bounded, to_iso

# Bounded k — the top-signals cut. NET-NEW default; a profile may tighten later.
DEFAULT_TOP_K: int = 5

_DEFERRED_REASON = (
    "signal_importance compute ready (168-06); concrete quant/correlation-lead-lag "
    "reader seam wired in 169 — deferred, non-downgrading (not a runtime outage)"
)


def _normalize_rows(raw: Any) -> list[dict]:
    """Coerce a candidate-signal read into a list of row dicts (defensive)."""
    rows: Iterable
    if raw is None:
        return []
    if isinstance(raw, dict) and "signals" in raw:
        rows = raw.get("signals") or []
    elif isinstance(raw, dict):
        rows = [{"signal_id": k, "importance": v} for k, v in raw.items()]
    else:
        rows = raw
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _to_signal(row: dict, *, excluded_reason: str | None) -> SignalFacet | None:
    """Map one row to a SignalFacet; ``None`` when the row is unusable (honest skip)."""
    signal_id = row.get("signal_id") or row.get("id") or row.get("name")
    importance = bounded(row.get("importance", row.get("score")), 0.0, 1.0)
    if signal_id is None or importance is None:
        return None
    return SignalFacet(signal_id=str(signal_id), importance=importance, excluded_reason=excluded_reason)


def compose_signal_importance(ctx) -> tiers.FacetOutcome:
    reader = getattr(ctx.deps, "signal_reader", None)
    if reader is None:
        # Not-yet-wired concrete seam (169) — deferred, non-downgrading.
        return tiers.FacetOutcome(
            name="signal_importance",
            ok=False,
            deferred=True,
            integrity=FacetIntegrity.UNKNOWN,
            reason=_DEFERRED_REASON,
            value=None,
        )

    req = ctx.request
    raw = reader.candidate_signals(req.country, req.domain_slug, knowledge_time=to_iso(req.knowledge_time))
    if raw is None:
        # Seam present but the provider returned nothing measurable — IMPORTANT
        # down => pack partial + warning (honest-empty, never fabricated).
        return tiers.FacetOutcome(
            name="signal_importance",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="signal reader returned no result (candidate signals unavailable)",
        )

    rows = _normalize_rows(raw)
    k = _resolve_k(ctx)

    # Partition eligible vs explicitly-ineligible, deterministically.
    eligible: list[dict] = []
    ineligible: list[SignalFacet] = []
    for row in rows:
        if row.get("eligible") is False:
            reason = str(row.get("exclude_reason") or "ineligible")
            facet = _to_signal(row, excluded_reason=reason)
            if facet is not None:
                ineligible.append(facet)
            continue
        eligible.append(row)

    # Deterministic ranking: importance desc, signal_id asc as the stable tiebreak.
    def _rank_key(r: dict):
        imp = bounded(r.get("importance", r.get("score")), 0.0, 1.0)
        sid = str(r.get("signal_id") or r.get("id") or r.get("name") or "")
        return (-(imp if imp is not None else 0.0), sid)

    eligible_sorted = sorted(eligible, key=_rank_key)

    top: list[SignalFacet] = []
    excluded: list[SignalFacet] = list(ineligible)
    for idx, row in enumerate(eligible_sorted):
        if idx < k:
            facet = _to_signal(row, excluded_reason=None)
            if facet is not None:
                top.append(facet)
        else:
            facet = _to_signal(row, excluded_reason=f"rank > top_{k}")
            if facet is not None:
                excluded.append(facet)

    return tiers.FacetOutcome(
        name="signal_importance",
        ok=True,
        integrity=FacetIntegrity.NEUTRAL,
        value={"top": tuple(top), "excluded": tuple(excluded)},
    )


def _resolve_k(ctx) -> int:
    """Resolve the bounded top-k (a profile/request may tighten; default DEFAULT_TOP_K)."""
    k = getattr(ctx.deps, "signal_top_k", None)
    try:
        k_int = int(k) if k is not None else DEFAULT_TOP_K
    except (TypeError, ValueError):
        k_int = DEFAULT_TOP_K
    return max(1, k_int)
