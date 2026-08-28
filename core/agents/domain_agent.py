"""Phase 169 Plan 02 (D-04 / D-07 / D-10) — generic DomainAgent base.

The shared extraction the AGENT-3 finding calls for: today there is NO base, only
12 near-verbatim 143-line `agents/<slug>_domain_analyst/agent.py` copies. This base
carries the common workflow the concrete analysts subclass; the per-domain knowledge
comes from a typed `DomainDefinition` (domain_definition.py).

Path choice (Pattern 1): this file lives at `core/agents/domain_agent.py`,
deliberately OUTSIDE the `agents/<slug>_domain_analyst/agent.py` static-grep path,
so the per-slug engine-lock guard never reads it. Its own engine-lock is closed by
`tests/agents/test_domain_base_engine_lock.py` (Task 3) — moving logic upward must
NOT hollow out the ban.

Two surfaces coexist (Pitfall 1 / A2 — coexist, do not evolve fixtures):
- **Legacy `invoke(Domain) -> SpecialistResponse`** — reproduces the 143-line agent's
  60-90 word narrative verbatim, keyed on `self.DOMAIN`/`self.DOMAIN_SLUG`, so the
  existing guard + per-analyst invoke tests stay green.
- **Net-new `assess(pack) -> DomainAssessment`** — the deterministic, LLM-free
  interpretation path (AGV-10). It COPIES level/momentum/surprise from the typed pack
  (never recomputes — engine-lock), classifies `current_state` over the
  DomainDefinition `reasoning_rules` thresholds, builds real falsifiable `claims[]`,
  reuses `core/evidence/tiers` for integrity -> abstention (never a second policy),
  sources `state_version` from `PackIdentity.state_version` (D-10), and threads
  `pack.knowledge_time` immutably — NO wall-clock re-stamp anywhere on the assess path
  (Pitfall 4 / Constitution 18).

The base is LLM-free (no openai/anthropic/litellm — Pitfall 5); `max_cost_usd` stays
0.0; the reproducibility manifest records `model="deterministic"`.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# VM107-local input/output narrative contract (unchanged legacy surface)
from contracts.economic_intelligence.domain import Domain
from contracts.economic_intelligence.specialist_response import SpecialistResponse

# Shared fingpt_core contracts (Plan 169-01 + 168)
from fingpt_core.contracts.assessment import (
    AbstentionOutcome,
    Claim,
    ClaimClass,
    Confidence,
    DomainAssessment,
    Horizon,
    ReproducibilityManifest,
    compute_claim_id,
)
from fingpt_core.contracts.evidence_pack import DomainEvidencePack, FacetIntegrity

# Deterministic degradation authority — reuse, never re-derive (Pattern 5)
from core.evidence import tiers
from core.evidence.tiers import FacetOutcome

from core.agents.domain_definition import DomainDefinition

_TOP_INDICATOR_COUNT = 5
_TOP_DRIVER_COUNT = 3

# Integrity states that mark a facet as "down" (Unknown/failure), vs a measured NEUTRAL.
_DOWN_INTEGRITY: frozenset[FacetIntegrity] = frozenset(
    {
        FacetIntegrity.UNKNOWN,
        FacetIntegrity.STALE,
        FacetIntegrity.UNAVAILABLE,
        FacetIntegrity.INSUFFICIENT_HISTORY,
        FacetIntegrity.PROVIDER_FAILURE,
    }
)

# Map the tier engine's abstain code -> the assessment's typed abstention outcome.
_ABSTAIN_MAP: dict[str, AbstentionOutcome] = {
    tiers.STATE_STALE: AbstentionOutcome.STATE_STALE,
    tiers.INSUFFICIENT_EVIDENCE: AbstentionOutcome.INSUFFICIENT_EVIDENCE,
}


class _SafeDict(dict):
    """format_map helper — leaves an unknown `{key}` literal instead of raising."""

    def __missing__(self, key: str) -> str:  # noqa: D105
        return "{" + key + "}"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}"


def _clamp_unit(value: float | None) -> float | None:
    """Bound a copied value into the contract's [-1, 1] range (bounding, not computing)."""
    if value is None:
        return None
    return max(-1.0, min(1.0, value))


class DomainAgent:
    """Generic domain analyst base (D-04) — legacy invoke + net-new assess.

    Concrete analysts (Plan 169-06) become config-only subclasses that set the
    `DOMAIN`/`DOMAIN_SLUG`/`AGENT_ID` class attrs (kept per-file for the static grep)
    and supply a `DomainDefinition` (loaded from the `domain_definition:` profile block,
    Plan 169-04).
    """

    # Overridden per concrete subclass (kept on the subclass for the per-slug grep).
    DOMAIN: str = ""
    DOMAIN_SLUG: str = ""
    AGENT_ID: str = ""
    AGENT_VERSION: str = "1.0.0"

    def __init__(self, domain_definition: DomainDefinition | None = None) -> None:
        # Optional so the legacy zero-arg instantiation (`Analyst()`) still works for
        # the invoke() surface; assess() resolves the definition lazily if not passed.
        self._domain_definition = domain_definition

    # ------------------------------------------------------- legacy invoke
    def invoke(
        self, domain: Domain, context: dict | None = None
    ) -> SpecialistResponse:
        """Reproduce the legacy 60-90 word narrative response (unchanged behavior)."""
        assert domain.slug == self.DOMAIN_SLUG, (
            f"{type(self).__name__} received domain.slug={domain.slug!r} — "
            f"expected {self.DOMAIN_SLUG!r}"
        )

        narrative = self._compose_narrative(domain)
        citations = [
            ind.indicator_id for ind in domain.top_indicators[:_TOP_INDICATOR_COUNT]
        ]
        evidence = [
            {
                "driver": d.name,
                "direction": d.direction,
                "contribution": d.contribution,
            }
            for d in domain.drivers
        ]
        limitations = self._derive_limitations(domain)
        related = self._related_entities(domain)

        return SpecialistResponse(
            answer=narrative,
            confidence=domain.confidence,
            citations=citations,
            evidence=evidence,
            limitations=limitations,
            related_entities=related,
        )

    def _compose_narrative(self, domain: Domain) -> str:
        """Deterministic 60-90 word headline (moved verbatim from the 143-line copy)."""
        top_drivers = domain.drivers[:_TOP_DRIVER_COUNT]
        top_indicators = domain.top_indicators[:_TOP_DRIVER_COUNT]

        driver_phrase = (
            ", ".join(
                f"{d.name} ({d.direction}, contribution {d.contribution:+.2f})"
                for d in top_drivers
            )
            if top_drivers
            else "no individual drivers stand out at the moment"
        )
        indicator_phrase = (
            ", ".join(ind.title for ind in top_indicators)
            if top_indicators
            else "no primary indicators currently published"
        )
        tailwind_phrase = (
            f"Tailwinds: {'; '.join(domain.tailwinds[:2])}."
            if domain.tailwinds
            else "Tailwinds are limited."
        )
        headwind_phrase = (
            f"Headwinds: {'; '.join(domain.headwinds[:2])}."
            if domain.headwinds
            else "Headwinds are limited."
        )

        return (
            f"The {self.DOMAIN} domain is currently {domain.current_state} "
            f"with a health score of {domain.health_score:.0f}/100 and a "
            f"trend reading of {domain.trend_score:+.0f}, against a breadth "
            f"of {domain.breadth_score:.0f}/100; risk level reads as "
            f"{domain.risk_level} at confidence {domain.confidence:.2f}. "
            f"Top drivers behind the print: {driver_phrase}. Primary "
            f"indicators powering the read: {indicator_phrase}. "
            f"{tailwind_phrase} {headwind_phrase} The state reading reflects "
            f"the joint signal from level, momentum, and breadth; specialists "
            f"should drill into individual contributors for the driver story."
        )

    def _derive_limitations(self, domain: Domain) -> list[str]:
        lims: list[str] = []
        if domain.confidence < 0.5:
            lims.append(
                f"upstream confidence degraded ({domain.confidence:.2f}) "
                f"— interpret cautiously"
            )
        if not domain.drivers:
            lims.append("no drivers available")
        if domain.breadth_score < 40.0:
            lims.append(
                "narrow basket participation — signal driven by few series"
            )
        if domain.status.value != "READY":
            lims.append(f"section status: {domain.status.value}")
        return lims

    def _related_entities(self, domain: Domain) -> list[str]:
        related: list[str] = [f"domain:{domain.slug}"]
        for pillar in domain.primary_pillars:
            related.append(f"pillar:{pillar}")
        for ind in domain.top_indicators[:_TOP_DRIVER_COUNT]:
            related.append(f"indicator:{ind.indicator_id}")
        return related

    # ------------------------------------------------------- net-new assess
    def assess(
        self,
        pack: DomainEvidencePack,
        *,
        knowledge_time: datetime | None = None,
    ) -> DomainAssessment:
        """Narrate a DomainEvidencePack into a falsifiable DomainAssessment (AGV-10).

        Deterministic + LLM-free (D-07). State facts are COPIED from the pack (engine
        lock); `current_state` + `claims[]` + `invalidation_conditions` come from the
        DomainDefinition `reasoning_rules`; integrity/abstention reuse the tier engine;
        `state_version` is `pack.identity.state_version` (D-10); `knowledge_time` is
        threaded immutably (no wall-clock re-stamp — Pitfall 4).
        """
        defn = self._resolve_definition()

        # (0) immutable identity / scope + knowledge_time (never a wall-clock read)
        domain_name = self.DOMAIN or pack.identity.domain_slug
        geography_id = pack.identity.country
        geography_type = "country"
        state_version = pack.identity.state_version  # D-10 — no parallel counter
        kt = knowledge_time if knowledge_time is not None else pack.knowledge_time

        # (1) COPY level/momentum/surprise from the typed pack (never recompute)
        level = _clamp_unit(pack.domain_state.score)
        momentum = _clamp_unit(pack.state_diff.delta_score)
        surprise = None  # no surprise facet on the pack — Unknown, not computed-as-zero

        # (2) deterministic current_state classifier over reasoning_rules thresholds
        current_state = defn.reasoning_rules.classify(level, momentum, surprise)

        # (3) decomposed confidence — copied/passed-through from the pack
        base_c = pack.domain_state.confidence if pack.domain_state.confidence is not None else 0.5
        data_c = base_c
        if pack.data_quality is not None and pack.data_quality.coverage is not None:
            data_c = pack.data_quality.coverage
        confidence = Confidence(
            data=data_c,
            state_model=base_c,
            interpretation=base_c,
            forecast=base_c,
            overall=base_c,
        )

        # (4) integrity_state + abstention outcome via the tier engine (reuse, D-07)
        integrity_state = pack.domain_state.integrity
        abstention_outcome = self._derive_abstention(pack)

        # (5) evidence linkage (signals + contributors) for claims + manifest
        evidence_refs = tuple(s.signal_id for s in pack.top_signals)
        evidence_ids = evidence_refs + tuple(c.name for c in pack.top_contributors)

        # (6) build real, non-empty falsifiable claims from the templates
        fill_ctx = _SafeDict(
            state=current_state,
            current_state=current_state,
            level=_fmt(level),
            momentum=_fmt(momentum),
            surprise=_fmt(surprise),
            domain=domain_name,
            geography=geography_id,
        )
        claims = tuple(
            self._build_claim(
                tmpl=tmpl,
                fill_ctx=fill_ctx,
                domain_name=domain_name,
                geography_id=geography_id,
                state_version=state_version,
                knowledge_time=kt,
                confidence=base_c,
                evidence_refs=evidence_refs,
            )
            for tmpl in defn.reasoning_rules.claim_templates
        )
        invalidation_conditions = tuple(
            cond.format_map(fill_ctx) for cond in defn.reasoning_rules.invalidation_conditions
        )

        # (7) assessment horizon + reproducibility manifest
        horizon = _first_horizon(defn.horizons)
        manifest = ReproducibilityManifest(
            agent_version=self.AGENT_VERSION,
            model="deterministic",  # D-07 — LLM-free; max_cost_usd stays 0.0
            prompt_version="deterministic-v1",
            state_version=state_version,
            feature_set_version=f"dd-{defn.domain_definition_version}",
            knowledge_version=defn.knowledge_version,
            tool_versions=(),
            evidence_ids=evidence_ids,
            knowledge_time=kt,
            execution_time=kt,  # deterministic path — threaded, never wall-clock re-stamped
        )

        return DomainAssessment(
            domain=domain_name,
            geography_id=geography_id,
            geography_type=geography_type,
            sector=None,
            state_version=state_version,
            horizon=horizon,
            level=level,
            momentum=momentum,
            surprise=surprise,
            confidence=confidence,
            integrity_state=integrity_state,
            claims=claims,
            invalidation_conditions=invalidation_conditions,
            abstention_outcome=abstention_outcome,
            manifest=manifest,
            knowledge_time=kt,
        )

    # ------------------------------------------------------- assess internals
    def _resolve_definition(self) -> DomainDefinition:
        """Return the DomainDefinition, lazily loading from the profile if not injected."""
        if self._domain_definition is not None:
            return self._domain_definition
        profile_path = (
            Path(__file__).resolve().parent.parent.parent
            / "registry"
            / "agent_profile"
            / f"vm107.{self.DOMAIN_SLUG}_domain_analyst.yaml"
        )
        try:
            self._domain_definition = DomainDefinition.from_profile(profile_path)
        except Exception as exc:  # clear, actionable error — no silent stub
            raise RuntimeError(
                f"{type(self).__name__}.assess requires a DomainDefinition: no "
                f"'domain_definition:' block loadable from {profile_path} "
                f"({exc}). Pass domain_definition=... or add the block (Plan 169-04)."
            ) from exc
        return self._domain_definition

    def _derive_abstention(self, pack: DomainEvidencePack) -> AbstentionOutcome | None:
        """Map pack integrity -> a typed abstention via the tier engine (reuse, D-07)."""
        contributions: list[str] = []
        abstain_code: str | None = None
        for rec in pack.pack_integrity.facets:
            if rec.facet not in tiers.TIER_MAP:
                continue
            down = rec.integrity in _DOWN_INTEGRITY
            outcome = FacetOutcome(
                name=rec.facet,
                ok=not down,
                integrity=rec.integrity,
                reason=rec.reason,
            )
            decision = tiers.apply_tier(rec.facet, outcome)
            contributions.append(decision.pack_outcome_contribution)
            if decision.abstain_code and abstain_code is None:
                abstain_code = decision.abstain_code

        combined = tiers.combine_pack_outcome(contributions)
        degraded = pack.pack_integrity.pack_outcome == "degraded" or combined == "degraded"
        if not degraded:
            return None
        return _ABSTAIN_MAP.get(abstain_code, AbstentionOutcome.INSUFFICIENT_EVIDENCE)

    def _build_claim(
        self,
        *,
        tmpl,
        fill_ctx: _SafeDict,
        domain_name: str,
        geography_id: str,
        state_version: str,
        knowledge_time: datetime,
        confidence: float,
        evidence_refs: tuple[str, ...],
    ) -> Claim:
        subject = tmpl.subject.format_map(fill_ctx)
        predicate = tmpl.predicate.format_map(fill_ctx)
        obj = tmpl.object.format_map(fill_ctx)
        claim_class = ClaimClass(tmpl.claim_class)
        horizon = Horizon(tmpl.horizon)
        claim_id = compute_claim_id(
            domain_name,
            geography_id,
            claim_class,
            subject,
            predicate,
            obj,
            state_version,
            knowledge_time,
        )
        return Claim(
            claim_id=claim_id,
            claim_class=claim_class,
            subject=subject,
            predicate=predicate,
            object=obj,
            horizon=horizon,
            confidence=confidence,
            evidence_refs=evidence_refs,
            invalidation_conditions=tuple(
                cond.format_map(fill_ctx) for cond in tmpl.invalidation_conditions
            ),
            assumptions=tmpl.assumptions,
            generated_by=self.AGENT_ID,
            state_version=state_version,
        )


def _first_horizon(horizons: tuple[str, ...]) -> Horizon:
    """The assessment's primary horizon — first declared, defaulting to NOWCAST."""
    for name in horizons:
        try:
            return Horizon(name)
        except ValueError:
            continue
    return Horizon.NOWCAST


__all__ = ["DomainAgent"]
