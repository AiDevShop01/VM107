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
from core.evidence.facets import bounded, parse_dt, to_iso

_LABEL_KEYS = ("label", "current_state", "state", "regime_label")


def _to_state_facet(state: dict, state_version: str) -> DomainStateFacet:
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
        integrity=FacetIntegrity.NEUTRAL,
    )


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

    if status != "ok" or not current:
        reason = meta.get("reason") or f"domain-state read status={status!r}"
        integrity = FacetIntegrity.STALE if status == "stale" else FacetIntegrity.UNAVAILABLE
        return tiers.FacetOutcome(
            name="domain_state", ok=False, integrity=integrity, reason=reason
        )

    state_version = str(
        meta.get("state_version")
        or current.get("state_version")
        or f"{req.country}:{req.domain_slug}:current"
    )
    facet = _to_state_facet(current, state_version)

    # previous state (for StateDiff). The provider is latest-only today (168-02):
    # a missing previous is an HONEST gap that StateDiff records, not fabricated.
    previous = data.get("previous")
    if previous:
        prev_version = str(
            previous.get("state_version")
            or meta.get("previous_state_version")
            or f"{state_version}:prev"
        )
        ctx.scratch["previous_state"] = _to_state_facet(previous, prev_version)

    return tiers.FacetOutcome(
        name="domain_state", ok=True, integrity=FacetIntegrity.NEUTRAL, value=facet
    )
