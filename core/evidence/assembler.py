"""Phase 168 Plan 05 — EvidencePackAssembler (AGV-06 core).

A stateless orchestrator that composes the determinism substrate in a fixed
canonical order and emits a typed, frozen ``DomainEvidencePack``, applying
per-facet tier degradation (D-07) so nothing hard-fails (D-02).

Analog: ``core/agents/decision_framework/framework.py::Framework`` +
``PythonEngineResult`` — the closest existing "stateless orchestrator runs N
evaluators in a canonical fixed order and aggregates into a frozen result with
graceful partial-context" shape on VM107. Mirrored here:

- ``ASSEMBLY_ORDER`` — the module-level 7-facet fixed order (framework's
  ``CATEGORY_ORDER`` analog).
- ``_validate_boot_invariants`` at ``__init__`` — asserts ASSEMBLY_ORDER covers
  the DomainEvidencePack facet set and every facet has a registered composer +
  a declared tier; raises on mismatch (framework's boot-invariant analog).
- ``assemble(...)`` — iterates ASSEMBLY_ORDER, calls each registered composer
  inside a try that converts ANY exception into a typed FacetIntegrity.
  PROVIDER_FAILURE (never propagate — D-02), applies ``tiers.apply_tier``,
  accumulates ``pack_integrity`` + ``pack_outcome``, and returns a frozen
  ``DomainEvidencePack`` carrying ``knowledge_time`` from the request.

Facet composers (the composition seam):
- REQUIRED  ``domain_state`` / ``state_diff`` — wired to the typed VM102
  ``get_domain_state`` read (168-02) in Plan-05 Task 2 (``facets/``).
- IMPORTANT ``contribution`` — wired to the typed contribution read in Task 2.
- ENRICHMENT ``contradiction`` — wraps the existing ContradictionEngine in Task 2.
- The net-new ``signal_importance`` / ``historical_context`` / ``prior_assessment``
  facets are registered as DEFERRED placeholders here (recorded "pending 168-06",
  non-downgrading) so the assembler is complete + no-brick now; 168-06 replaces
  them with real composers.

Every VM102 read a composer performs routes through a typed client method (G10)
— never a raw parquet/DB store, never ``compute_domain()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

from fingpt_core.contracts.evidence_pack import (
    ContradictionFacet,
    ContributorFacet,
    DataQualityFacet,
    DomainEvidencePack,
    DomainStateFacet,
    FacetIntegrity,
    HistoricalPercentileFacet,
    PackIdentity,
    PackIntegrity,
    PriorAssessmentFacet,
    SignalFacet,
    StateDiffFacet,
)

from core.evidence import tiers

# ---------------------------------------------------------------------------
# Fixed canonical assembly order (AGV-06 / SPEC §1)
# ---------------------------------------------------------------------------

ASSEMBLY_ORDER: list[str] = [
    "domain_state",
    "state_diff",
    "contribution",
    "signal_importance",
    "contradiction",
    "historical_context",
    "prior_assessment",
]
ASSEMBLER_VERSION: int = 1

# Which DomainEvidencePack field(s) each facet populates — used both to build the
# pack and to prove (boot invariant) that every facet maps onto the real contract.
FACET_TO_PACK_FIELDS: dict[str, tuple[str, ...]] = {
    "domain_state": ("domain_state",),
    "state_diff": ("state_diff",),
    "contribution": ("top_contributors",),
    "signal_importance": ("top_signals", "excluded_signals"),
    "contradiction": ("contradictions",),
    "historical_context": ("historical_percentile",),
    "prior_assessment": ("prior_assessment",),
}

# Sentinel state_version for a REQUIRED DomainState that could not be read — the
# degraded facet is still a VALID DomainStateFacet (D-03), carrying its integrity.
_UNAVAILABLE_VERSION: str = "unavailable"


# ---------------------------------------------------------------------------
# Assembly request / deps / context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssemblyRequest:
    """What to assemble a pack for + the run's point-in-time as-of."""

    country: str
    domain_slug: str
    knowledge_time: datetime


@dataclass
class FacetDeps:
    """Injected typed seams the default composers read through (G10).

    Each is optional; a composer whose seam is ``None`` returns a typed
    UNAVAILABLE failure (honest-empty) rather than raising — so an unconfigured
    assembler degrades, never bricks. Concrete seams are supplied by the
    registry / assembler wiring (Task 2 facets + 169).
    """

    domain_state_reader: Any | None = None
    contribution_reader: Any | None = None
    contradiction_engine: Any | None = None
    # Detection inputs (predicted/actual/sigma_historical/active_beliefs) the
    # ENRICHMENT contradiction facet feeds to the wired-as-is ContradictionEngine.
    # Concrete plumbing (transmission engine + VM101) is a 169 dependency.
    contradiction_inputs: dict[str, Any] | None = None

    # -- 168-06 net-new facet seams (G10; concrete adapters are a 169 dependency) --
    # signal_importance (IMPORTANT): typed candidate-signal read (quant/lead-lag).
    signal_reader: Any | None = None
    signal_top_k: int | None = None
    # historical_context (ENRICHMENT): VM102 percentile read (always-available sub-path).
    percentile_reader: Any | None = None
    # evidence_ranking (ENRICHMENT, prior_assessment slot): Qdrant retrieval + the
    # SourceHealthRegistry consulted hits-first (only `if not hits`).
    evidence_reader: Any | None = None
    source_health: Any | None = None


@dataclass
class AssemblyContext:
    """Threaded to each composer; accumulates outcomes + cross-facet scratch."""

    request: AssemblyRequest
    deps: FacetDeps
    outcomes: dict[str, tiers.FacetOutcome] = field(default_factory=dict)
    scratch: dict[str, Any] = field(default_factory=dict)


Composer = Callable[[AssemblyContext], tiers.FacetOutcome]


# ---------------------------------------------------------------------------
# Default deferred-placeholder composers (net-new facets land in 168-06)
# ---------------------------------------------------------------------------


def _deferred_composer(facet_name: str, reason: str = "pending 168-06") -> Composer:
    """A not-yet-built facet: recorded honestly, non-downgrading (deferred)."""

    def _c(ctx: AssemblyContext) -> tiers.FacetOutcome:
        return tiers.FacetOutcome(
            name=facet_name,
            ok=False,
            deferred=True,
            integrity=FacetIntegrity.UNKNOWN,
            reason=reason,
            value=None,
        )

    return _c


def _unconfigured_composer(facet_name: str) -> Composer:
    """Default for a reuse facet whose typed seam is not wired — honest UNAVAILABLE."""

    def _c(ctx: AssemblyContext) -> tiers.FacetOutcome:
        return tiers.FacetOutcome(
            name=facet_name,
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no composer/seam configured",
            value=None,
        )

    return _c


def _default_composers() -> dict[str, Composer]:
    """Base registration.

    Plan-05 Task 2 overrides the four reuse facets (domain_state / state_diff /
    contribution / contradiction) with real typed composers from
    ``core.evidence.facets``; if that package is importable they are wired here
    automatically, else the honest UNAVAILABLE defaults stand.
    """
    composers: dict[str, Composer] = {
        "domain_state": _unconfigured_composer("domain_state"),
        "state_diff": _unconfigured_composer("state_diff"),
        "contribution": _unconfigured_composer("contribution"),
        "signal_importance": _deferred_composer("signal_importance"),
        "contradiction": _unconfigured_composer("contradiction"),
        "historical_context": _deferred_composer("historical_context"),
        "prior_assessment": _deferred_composer("prior_assessment"),
    }
    try:  # Task 2 facets — wired-as-available so Task 1 stays green standalone.
        from core.evidence import facets

        composers.update(facets.reuse_composers())
        # 168-06 net-new REAL composers replace the deferred-placeholder slots
        # (signal_importance / historical_context / prior_assessment) over the
        # same seam — no structural assembler change. Each degrades gracefully
        # (deferred/omit) when its concrete reader seam is absent (169 wiring).
        composers.update(facets.netnew_composers())
    except Exception:  # pragma: no cover - defensive: never let wiring brick import
        pass
    return composers


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


class EvidencePackAssembler:
    """Compose a typed DomainEvidencePack in fixed order, per-facet tier-degraded.

    Stateless after construction; one instance per process is fine.
    """

    def __init__(
        self,
        composers: Mapping[str, Composer] | None = None,
        assembly_order: list[str] | None = None,
    ):
        self._order: list[str] = list(assembly_order) if assembly_order is not None else list(ASSEMBLY_ORDER)
        self._composers: dict[str, Composer] = _default_composers()
        if composers:
            self._composers.update(composers)
        self._validate_boot_invariants()

    def _validate_boot_invariants(self) -> None:
        """Fail-fast: ASSEMBLY_ORDER must cover exactly the canonical facet set,
        every ordered facet must have a tier + a composer, and every facet must
        map onto a real DomainEvidencePack field (contract-coupling)."""
        order_set = set(self._order)
        if order_set != set(tiers.CANONICAL_FACETS):
            raise RuntimeError(
                "EvidencePackAssembler boot invariant violated: assembly order "
                f"{sorted(order_set)} does not cover the canonical facet set "
                f"{sorted(tiers.CANONICAL_FACETS)}."
            )
        if len(self._order) != len(tiers.CANONICAL_FACETS):
            raise RuntimeError(
                "EvidencePackAssembler boot invariant violated: assembly order has "
                f"duplicate/missing facets ({self._order})."
            )
        pack_fields = set(DomainEvidencePack.model_fields)
        for facet in self._order:
            if facet not in tiers.TIER_MAP:
                raise RuntimeError(f"boot invariant: facet '{facet}' has no declared tier.")
            if facet not in self._composers:
                raise RuntimeError(f"boot invariant: facet '{facet}' has no registered composer.")
            for pack_field in FACET_TO_PACK_FIELDS[facet]:
                if pack_field not in pack_fields:
                    raise RuntimeError(
                        f"boot invariant: facet '{facet}' maps to unknown pack field '{pack_field}'."
                    )

    def assemble(self, request: AssemblyRequest, *, deps: FacetDeps | None = None) -> DomainEvidencePack:
        """Run every facet in ASSEMBLY_ORDER and emit a frozen DomainEvidencePack.

        No facet failure raises out of this method (D-02): any exception a
        composer throws is converted to a typed PROVIDER_FAILURE outcome.
        """
        ctx = AssemblyContext(request=request, deps=deps or FacetDeps())
        decisions: dict[str, tiers.TierDecision] = {}
        for facet in self._order:
            composer = self._composers[facet]
            try:
                outcome = composer(ctx)
            except Exception as exc:  # D-02 no-brick — convert, never propagate.
                outcome = tiers.FacetOutcome(
                    name=facet,
                    ok=False,
                    integrity=FacetIntegrity.PROVIDER_FAILURE,
                    reason=f"{type(exc).__name__}: {exc}",
                    value=None,
                )
            ctx.outcomes[facet] = outcome
            decisions[facet] = tiers.apply_tier(facet, outcome)
        return self._build_pack(ctx, decisions)

    # -- pack assembly ------------------------------------------------------

    def _build_pack(
        self, ctx: AssemblyContext, decisions: dict[str, tiers.TierDecision]
    ) -> DomainEvidencePack:
        out = ctx.outcomes

        # REQUIRED spine — always a VALID sub-model, degraded-but-present (D-03).
        ds = out["domain_state"]
        if ds.ok and isinstance(ds.value, DomainStateFacet):
            domain_state = ds.value
        else:
            domain_state = DomainStateFacet(state_version=_UNAVAILABLE_VERSION, integrity=ds.integrity)

        sd = out["state_diff"]
        if sd.ok and isinstance(sd.value, StateDiffFacet):
            state_diff = sd.value
        else:
            state_diff = StateDiffFacet(integrity=sd.integrity)

        previous_state = ctx.scratch.get("previous_state")
        if previous_state is not None and not isinstance(previous_state, DomainStateFacet):
            previous_state = None

        # IMPORTANT / ENRICHMENT degraded-omittable facets.
        contribution = out["contribution"]
        top_contributors: tuple[ContributorFacet, ...] = (
            tuple(contribution.value) if (contribution.ok and contribution.value) else ()
        )

        si = out["signal_importance"]
        if si.ok and isinstance(si.value, Mapping):
            top_signals: tuple[SignalFacet, ...] = tuple(si.value.get("top", ()))
            excluded_signals: tuple[SignalFacet, ...] = tuple(si.value.get("excluded", ()))
        else:
            top_signals = ()
            excluded_signals = ()

        cd = out["contradiction"]
        contradictions: tuple[ContradictionFacet, ...] = (
            tuple(cd.value) if (cd.ok and cd.value) else ()
        )

        hc = out["historical_context"]
        historical_percentile = (
            hc.value if (hc.ok and isinstance(hc.value, HistoricalPercentileFacet)) else None
        )

        pa = out["prior_assessment"]
        prior_assessment = (
            pa.value if (pa.ok and isinstance(pa.value, PriorAssessmentFacet)) else None
        )

        data_quality = ctx.scratch.get("data_quality")
        if data_quality is not None and not isinstance(data_quality, DataQualityFacet):
            data_quality = None

        identity = PackIdentity(
            country=ctx.request.country,
            domain_slug=ctx.request.domain_slug,
            state_version=domain_state.state_version,
        )
        contributions = [decisions[f].pack_outcome_contribution for f in self._order]
        pack_outcome = tiers.combine_pack_outcome(contributions)
        manifest = PackIntegrity(
            pack_outcome=pack_outcome,
            facets=tuple(decisions[f].record for f in self._order),
        )

        return DomainEvidencePack(
            identity=identity,
            domain_state=domain_state,
            state_diff=state_diff,
            knowledge_time=ctx.request.knowledge_time,
            pack_integrity=manifest,
            previous_state=previous_state,
            top_contributors=top_contributors,
            top_signals=top_signals,
            excluded_signals=excluded_signals,
            contradictions=contradictions,
            historical_percentile=historical_percentile,
            prior_assessment=prior_assessment,
            data_quality=data_quality,
        )
