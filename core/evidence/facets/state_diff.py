"""Phase 168 Plan 05 Task 2 — StateDiff facet composer (REQUIRED).

Composes the current vs previous ``DomainStateFacet`` (produced by the
domain_state composer) into the ``StateDiffFacet`` sub-model. StateDiff is
REQUIRED — when it cannot be composed (domain_state down, or no previous state
available) it returns an HONEST typed failure so the assembler degrades the pack
and the agent abstains ``INSUFFICIENT_EVIDENCE`` (never a fabricated diff).

State identity references the VM102 ``state_version`` carried on the facets — it
does NOT mint a new versioning scheme (G6 versioned-state history lands in 169).
"""

from __future__ import annotations

from fingpt_core.contracts.evidence_pack import FacetIntegrity, StateDiffFacet

from core.evidence import tiers
from core.evidence.facets import bounded


def compose_state_diff(ctx) -> tiers.FacetOutcome:
    ds_outcome = ctx.outcomes.get("domain_state")
    if ds_outcome is None or not ds_outcome.ok or ds_outcome.value is None:
        return tiers.FacetOutcome(
            name="state_diff",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="domain_state unavailable — cannot compose a diff",
        )

    current = ds_outcome.value  # DomainStateFacet
    previous = ctx.scratch.get("previous_state")
    if previous is None:
        # Honest gap: the provider is latest-only today; versioned previous-state
        # history is a 169 deliverable. Do NOT fabricate a no-change diff.
        return tiers.FacetOutcome(
            name="state_diff",
            ok=False,
            integrity=FacetIntegrity.INSUFFICIENT_HISTORY,
            reason="no previous state available (versioned history lands in 169)",
        )

    delta = None
    if current.score is not None and previous.score is not None:
        delta = bounded(current.score - previous.score, -2.0, 2.0)

    changed = current.label != previous.label
    if delta is not None and delta != 0.0:
        changed = True

    # Propagate the REQUIRED spine's point-in-time / degradation honesty onto the
    # diff (GAP 2): when the current DomainStateFacet is STALE (a degraded VM102
    # read) the diff of a degraded spine is itself STALE — not silently NEUTRAL;
    # a look-ahead flagged on domain_state is carried onto the diff's reason too.
    spine_stale = getattr(current, "integrity", None) == FacetIntegrity.STALE
    lookahead_reason = ctx.scratch.get("state_lookahead_reason")
    resolved_integrity = FacetIntegrity.STALE if spine_stale else FacetIntegrity.NEUTRAL

    facet = StateDiffFacet(
        changed=bool(changed),
        previous_label=previous.label,
        current_label=current.label,
        delta_score=delta,
        integrity=resolved_integrity,
    )
    return tiers.FacetOutcome(
        name="state_diff",
        ok=True,
        integrity=resolved_integrity,
        reason=lookahead_reason,
        value=facet,
    )
