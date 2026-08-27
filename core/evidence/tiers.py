"""Phase 168 Plan 05 Task 1 — tier engine + abstain policy (D-07 / D-02).

The tier engine is the deterministic degradation authority the
``EvidencePackAssembler`` consults for every facet. A facet's criticality
``FacetTier`` is declared UP FRONT (agent-catalogue/07 §5) so "which failure
sinks the pack" is a property of the contract, not a per-incident decision:

    | Tier       | Facets                          | Down =>                       |
    |------------|---------------------------------|-------------------------------|
    | REQUIRED   | domain_state, state_diff        | pack `degraded` + agent abstains (STATE_STALE / INSUFFICIENT_EVIDENCE) |
    | IMPORTANT  | contribution, signal_importance | pack emitted + warning (`partial`) |
    | ENRICHMENT | contradiction, historical_context, prior_assessment | facet omitted + reason (pack unaffected) |

Design locks honored here:
- **No-brick (D-02).** ``apply_tier`` never raises; the assembler converts ANY
  facet exception into a typed :class:`FacetOutcome` BEFORE this runs.
- **Honest-empty (07 §6a).** A failed read is recorded as a
  ``FacetIntegrityRecord`` (tier + integrity + reason) — never silently coerced
  to NEUTRAL/empty. The empty facet carries WHY.
- **Deferred != failed.** A net-new facet not yet built (168-06) is recorded as
  a deliberate ``deferred`` omission (UNKNOWN + reason) that does NOT downgrade
  the pack — an unbuilt facet is honest, not a runtime outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fingpt_core.contracts.evidence_pack import (
    FacetIntegrity,
    FacetIntegrityRecord,
    FacetTier,
)

# ---------------------------------------------------------------------------
# Tier map + canonical facet set (D-07)
# ---------------------------------------------------------------------------

TIER_MAP: dict[str, FacetTier] = {
    "domain_state": FacetTier.REQUIRED,
    "state_diff": FacetTier.REQUIRED,
    "contribution": FacetTier.IMPORTANT,
    "signal_importance": FacetTier.IMPORTANT,
    "contradiction": FacetTier.ENRICHMENT,
    "historical_context": FacetTier.ENRICHMENT,
    "prior_assessment": FacetTier.ENRICHMENT,
}

# The canonical facet set, in declared order — the assembler's ASSEMBLY_ORDER
# must cover exactly this set (boot invariant).
CANONICAL_FACETS: tuple[str, ...] = (
    "domain_state",
    "state_diff",
    "contribution",
    "signal_importance",
    "contradiction",
    "historical_context",
    "prior_assessment",
)

# ---------------------------------------------------------------------------
# Abstain codes (07 §5 — the agent MUST abstain when a REQUIRED facet is down)
# ---------------------------------------------------------------------------

STATE_STALE: str = "STATE_STALE"
INSUFFICIENT_EVIDENCE: str = "INSUFFICIENT_EVIDENCE"

# Which abstain code a REQUIRED facet raises when it is down.
ABSTAIN_BY_FACET: dict[str, str] = {
    "domain_state": STATE_STALE,
    "state_diff": INSUFFICIENT_EVIDENCE,
}

PackOutcome = Literal["success", "partial", "degraded"]
_OUTCOME_RANK: dict[str, int] = {"success": 0, "partial": 1, "degraded": 2}
_RANK_OUTCOME: dict[int, str] = {v: k for k, v in _OUTCOME_RANK.items()}


# ---------------------------------------------------------------------------
# Facet outcome — the typed result (or typed failure) a composer returns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FacetOutcome:
    """What a facet composer returns — a success value OR a typed failure.

    A composer NEVER raises out to the assembler contract; it returns this. On
    failure ``ok=False`` and ``integrity``/``reason`` explain WHY (honest-empty).
    ``value`` carries the populated pack sub-model(s) on success; the assembler
    maps it onto the DomainEvidencePack fields.

    ``deferred=True`` marks a facet that is not-yet-built (a planned 168-06
    facet) rather than a runtime outage — it is recorded but does not downgrade
    the pack outcome.
    """

    name: str
    ok: bool
    integrity: FacetIntegrity
    reason: str | None = None
    value: Any = None
    deferred: bool = False


@dataclass(frozen=True)
class TierDecision:
    """The tier engine's per-facet verdict."""

    facet: str
    disposition: Literal["include", "omit", "degrade"]
    pack_outcome_contribution: PackOutcome
    abstain_code: str | None
    record: FacetIntegrityRecord


# ---------------------------------------------------------------------------
# Tier decision — the deterministic degradation policy
# ---------------------------------------------------------------------------


def apply_tier(facet_name: str, outcome: FacetOutcome) -> TierDecision:
    """Return the deterministic degradation verdict for one facet.

    Pure — never raises, never performs IO. The disposition + pack-outcome
    contribution follow only from the facet's declared tier and whether the read
    succeeded (D-07).
    """
    if facet_name not in TIER_MAP:
        raise KeyError(f"unknown facet '{facet_name}' — not in TIER_MAP")
    tier = TIER_MAP[facet_name]

    # --- success: facet contributes, pack unaffected ---
    if outcome.ok:
        record = FacetIntegrityRecord(
            facet=facet_name, tier=tier, integrity=outcome.integrity, reason=outcome.reason
        )
        return TierDecision(facet_name, "include", "success", None, record)

    # --- deferred (not-yet-built 168-06 facet): recorded, non-downgrading ---
    if outcome.deferred:
        record = FacetIntegrityRecord(
            facet=facet_name,
            tier=tier,
            integrity=outcome.integrity or FacetIntegrity.UNKNOWN,
            reason=outcome.reason,
        )
        return TierDecision(facet_name, "omit", "success", None, record)

    # --- REQUIRED down: pack degraded + agent abstains ---
    if tier is FacetTier.REQUIRED:
        abstain = ABSTAIN_BY_FACET.get(facet_name)
        reason = f"{abstain}: {outcome.reason}" if abstain else outcome.reason
        record = FacetIntegrityRecord(
            facet=facet_name, tier=tier, integrity=outcome.integrity, reason=reason
        )
        return TierDecision(facet_name, "degrade", "degraded", abstain, record)

    # --- IMPORTANT down: pack emitted + warning (partial) ---
    if tier is FacetTier.IMPORTANT:
        record = FacetIntegrityRecord(
            facet=facet_name, tier=tier, integrity=outcome.integrity, reason=outcome.reason
        )
        return TierDecision(facet_name, "omit", "partial", None, record)

    # --- ENRICHMENT down: facet omitted + reason, pack unaffected ---
    record = FacetIntegrityRecord(
        facet=facet_name, tier=tier, integrity=outcome.integrity, reason=outcome.reason
    )
    return TierDecision(facet_name, "omit", "success", None, record)


def combine_pack_outcome(contributions: list[str]) -> PackOutcome:
    """Aggregate per-facet contributions into the pack outcome (worst-wins)."""
    if not contributions:
        return "success"
    worst = max(_OUTCOME_RANK[c] for c in contributions)
    return _RANK_OUTCOME[worst]  # type: ignore[return-value]
