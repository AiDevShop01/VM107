"""Phase 168 Plan 05 Task 2 — DomainState facet composer (REQUIRED, G10).

Fetches current (+ previous) DomainState through the typed VM102 read
``get_domain_state`` (168-02) and maps the ``{status, data, meta}`` envelope onto
the ``DomainStateFacet`` sub-model. On a missing/stale read it returns an HONEST
typed failure (STALE / UNAVAILABLE) — never coerced to a neutral/empty state
(07 §6a). The previous state is stashed on ``ctx.scratch['previous_state']`` for
the REQUIRED StateDiff facet to compose.

G10 lock: this composer reaches DomainState ONLY via the typed
``domain_state_reader.get_domain_state`` seam — it NEVER imports/calls the raw
domain-compute path and NEVER reads a raw parquet/DB store directly. The concrete
reader (an adapter over ``VM102Client.get_domain_state``) is injected by the
assembler / registry wiring (169); tests inject a fake transport-shaped seam.
"""

from __future__ import annotations

from typing import Any

from fingpt_core.contracts.evidence_pack import DomainStateFacet, FacetIntegrity

from core.evidence import tiers
from core.evidence.facets import bounded, is_latest_only_lookahead, parse_dt, to_iso

_LABEL_KEYS = ("label", "current_state", "state", "regime_label")

# Look-ahead honesty (Constitution 18), mirroring contribution.py's
# _LATEST_ONLY_REASON: the domain-state read is latest-only, so a run whose
# knowledge_time is materially in the past (VM102 meta.as_of_honored is False)
# served a look-ahead — recorded on the FacetOutcome.reason so pack_integrity is
# honest about the point-in-time risk on the REQUIRED spine.
_LATEST_ONLY_REASON = (
    "is_latest_only_flagged: latest-only domain-state read served a past as-of "
    "(look-ahead honesty — Constitution 18)"
)


def _to_state_facet(
    state: dict, state_version: str, integrity: FacetIntegrity = FacetIntegrity.NEUTRAL
) -> DomainStateFacet:
    """Map a raw DomainState dict to the typed facet (defensive on optional keys)."""
    label: Any = None
    for k in _LABEL_KEYS:
        if state.get(k) is not None:
            label = state.get(k)
            break
    return DomainStateFacet(
        state_version=str(state_version),
        as_of=parse_dt(state.get("as_of") or state.get("as_of_ts")),
        label=str(label) if label is not None else None,
        score=bounded(state.get("score"), -1.0, 1.0),
        confidence=bounded(state.get("confidence"), 0.0, 1.0),
        integrity=integrity,
    )


def _lookahead_reason(meta: dict, knowledge_time) -> str | None:
    """Return the look-ahead reason when a latest-only read served a past as-of.

    Prefers VM102's authoritative ``meta.as_of_honored`` signal (False => the
    requested knowledge_time was NOT honored, i.e. a "latest" read for a past
    as-of); falls back to comparing knowledge_time to now (contribution.py
    pattern) when the endpoint did not emit the signal.
    """
    latest_only = bool(meta.get("latest_only", True))
    if not latest_only:
        return None
    as_of_honored = meta.get("as_of_honored")
    if as_of_honored is False:
        return _LATEST_ONLY_REASON
    if as_of_honored is None and is_latest_only_lookahead(knowledge_time, latest_only=True):
        return _LATEST_ONLY_REASON
    return None


def compose_domain_state(ctx) -> tiers.FacetOutcome:
    reader = getattr(ctx.deps, "domain_state_reader", None)
    if reader is None:
        return tiers.FacetOutcome(
            name="domain_state",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no domain_state_reader configured (G10 typed seam)",
        )

    req = ctx.request
    envelope = reader.get_domain_state(
        req.country,
        req.domain_slug,
        knowledge_time=to_iso(req.knowledge_time),
        previous=True,
    ) or {}

    status = envelope.get("status")
    data = envelope.get("data") or {}
    meta = envelope.get("meta") or {}
    current = data.get("current")

    # VM102 status vocabulary is {"ok","degraded","unavailable"} — it NEVER emits
    # "stale" (the removed dead branch masked GAP 1). A MISSING current or an
    # explicit "unavailable" is an honest outage (ok=False / UNAVAILABLE). A
    # "degraded" read (confidence < 0.6) with a populated current is a LEGITIMATE
    # low-confidence RESULT — it must flow THROUGH as a STALE-tagged success, not
    # be discarded (GAP 1). Any unexpected status is treated conservatively as
    # UNAVAILABLE (we do not understand it — honest, never a silent pass).
    if not current or status == "unavailable":
        reason = meta.get("reason") or f"domain-state read status={status!r}"
        return tiers.FacetOutcome(
            name="domain_state", ok=False, integrity=FacetIntegrity.UNAVAILABLE, reason=reason
        )
    if status == "ok":
        resolved_integrity = FacetIntegrity.NEUTRAL
    elif status == "degraded":
        resolved_integrity = FacetIntegrity.STALE
    else:
        reason = meta.get("reason") or f"domain-state read unexpected status={status!r}"
        return tiers.FacetOutcome(
            name="domain_state", ok=False, integrity=FacetIntegrity.UNAVAILABLE, reason=reason
        )

    state_version = str(
        meta.get("state_version")
        or current.get("state_version")
        or f"{req.country}:{req.domain_slug}:current"
    )
    facet = _to_state_facet(current, state_version, resolved_integrity)

    # previous state (for StateDiff). The provider is latest-only today (168-02):
    # a missing previous is an HONEST gap that StateDiff records, not fabricated.
    previous = data.get("previous")
    if previous:
        prev_version = str(
            previous.get("state_version")
            or meta.get("previous_state_version")
            or f"{state_version}:prev"
        )
        ctx.scratch["previous_state"] = _to_state_facet(previous, prev_version, resolved_integrity)

    # Look-ahead honesty (GAP 2): record the reason on the SUCCESSFUL outcome
    # (apply_tier copies it onto the FacetIntegrityRecord) and stash it so the
    # REQUIRED state_diff facet can propagate the same point-in-time signal.
    lookahead_reason = _lookahead_reason(meta, req.knowledge_time)
    ctx.scratch["state_lookahead_reason"] = lookahead_reason

    return tiers.FacetOutcome(
        name="domain_state",
        ok=True,
        integrity=resolved_integrity,
        reason=lookahead_reason,
        value=facet,
    )
