"""Phase 170 Task 2 (D-02 / D-05) — the five deterministic lens rule bundles.

Each lens is a PURE first-matching-rule-wins classifier over its mapped
pre-compressed pack-facet slice (+ the typed `DomainAssessment`) — the direct
mirror of 169's `ReasoningRules.classify` / `StateRule.matches`. NO LLM, NO
wall-clock, NO recompute of engine state. An unmeasured (`None`) facet value can
NEVER satisfy a threshold (carry the `Unknown != match` discipline). Every lens
returns (verdict_label, confidence, rationale, RefinementTarget[]); it holds only
the reject/veto ceiling (05, D-05) — never ACCEPT-with-rewrite, never mutates the
assessment.

Lens -> facet slice map (SPEC §2 — each reads a DIFFERENT slice):
  Evidence  -> top_contributors, top_signals, data_quality   (EVIDENCE_UNSUPPORTED)
  Causality -> contradictions + CausalMechanismRegistry lookup (MECHANISM_UNREGISTERED)
  Market    -> state_diff, historical_percentile              (ALREADY_PRICED_IN)
  Risk      -> excluded_signals + assessment.invalidation_conditions (NO_INVALIDATION_CONDITION)
  Model     -> pack_integrity, domain_state, data_quality     (MODEL_DEGRADING)

Anti-pattern (Pitfall 2): NEVER call the strategy backtest veto/acceptance gates
from `refinement_orchestrator/` on an assessment — those take a `BacktestResult`.
"Reuse" here = reuse the PATTERN (a deterministic first-match gate) + the
CONTRACTS, not a literal call.
"""
from __future__ import annotations

from fingpt_core.contracts.assessment import DomainAssessment
from fingpt_core.contracts.evidence_pack import FacetIntegrity

from core.contracts.schemas import CanonicalIssueId, RefinementTarget
from core.causal.mechanism_registry import CausalMechanismRegistry

from core.agents.specialized_critic.lens_config import LensConfig

# (verdict_label, confidence, rationale, refinement_targets)
LensResult = tuple[str, float, str, list[RefinementTarget]]

# Integrity states that mark a facet as "down" (Unknown/failure), vs a measured NEUTRAL
# (mirror `core/agents/domain_agent.py` _DOWN_INTEGRITY).
_DOWN_INTEGRITY: frozenset[FacetIntegrity] = frozenset(
    {
        FacetIntegrity.UNKNOWN,
        FacetIntegrity.STALE,
        FacetIntegrity.UNAVAILABLE,
        FacetIntegrity.INSUFFICIENT_HISTORY,
        FacetIntegrity.PROVIDER_FAILURE,
    }
)


def _target(
    config: LensConfig,
    verdict_id: str,
    *,
    issue_id: str,
    issue: str,
    suggested_change: str,
    severity: str,
) -> RefinementTarget:
    """Build one typed `RefinementTarget` from the lens config coordinates."""
    return RefinementTarget(
        scope=config.scope,  # type: ignore[arg-type]
        canonical_issue_id=CanonicalIssueId(issue_id),
        target_field=config.target_field,
        issue=issue,
        issue_type=config.lens,
        severity=severity,  # type: ignore[arg-type]
        suggested_change=suggested_change,
        source_critic_verdict_id=verdict_id,
    )


# ------------------------------------------------------------------ Evidence
def _evidence(
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    contributors = facet_slice.get("top_contributors") or ()
    signals = facet_slice.get("top_signals") or ()
    data_quality = facet_slice.get("data_quality")
    coverage = data_quality.coverage if data_quality is not None else None
    support = len(contributors) + len(signals)

    if support < config.min_supporting_evidence:
        return (
            "REJECT",
            0.9,
            "no supporting contributors or signals back the claim — the read is "
            "unsupported by the pack's evidence (EVIDENCE_UNSUPPORTED).",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="EVIDENCE_UNSUPPORTED",
                    issue="claim has zero supporting contributors/signals in the evidence pack",
                    suggested_change="attach supporting contributors/signals or withdraw the claim",
                    severity="HIGH",
                )
            ],
        )
    # Unmeasured coverage (None) never satisfies the quality floor.
    if coverage is None or coverage < config.min_data_quality:
        return (
            "REFINE",
            0.7,
            f"evidence data-quality coverage {coverage!r} is below the floor "
            f"{config.min_data_quality} — the support is too thin to accept.",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="EVIDENCE_UNSUPPORTED",
                    issue=f"data_quality coverage {coverage!r} below floor {config.min_data_quality}",
                    suggested_change="improve coverage/completeness before asserting the claim",
                    severity="MEDIUM",
                )
            ],
        )
    return (
        "ACCEPT",
        float(coverage),
        f"claim is backed by {support} contributor/signal reference(s) at coverage "
        f"{coverage} — evidence supports the read.",
        [],
    )


# ------------------------------------------------------------------ Causality (SC#2)
def _causality(
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    contradictions = facet_slice.get("contradictions") or ()
    max_severity = max((c.severity for c in contradictions), default=0.0)

    # (1) Constitution 11: a directional read with NO registered transmission mechanism.
    for claim in assessment.claims:
        record = registry.lookup(
            assessment.domain, claim.claim_class, claim.subject, claim.predicate
        )
        if record is None:
            return (
                "REJECT",
                0.9,
                f"claim '{claim.subject} {claim.predicate} {claim.object}' asserts a "
                f"directional read with NO registered transmission mechanism "
                f"(Constitution 11 — correlation != causation); "
                f"{len(contradictions)} pack contradiction(s) noted.",
                [
                    _target(
                        config,
                        verdict_id,
                        issue_id="MECHANISM_UNREGISTERED",
                        issue=(
                            f"no registered transmission mechanism for "
                            f"({assessment.domain}, {claim.claim_class.value}, "
                            f"{claim.subject} -> {claim.predicate})"
                        ),
                        suggested_change=(
                            "register a plausible transmission mechanism in the "
                            "CausalMechanismRegistry or downgrade the claim to correlation-only"
                        ),
                        severity="HIGH",
                    )
                ],
            )

    # (2) Registered, but a strong pack contradiction challenges the transmission.
    if max_severity >= config.contradiction_severity_threshold:
        return (
            "REFINE",
            0.65,
            f"every claim maps to a registered mechanism, but a pack contradiction "
            f"(severity {max_severity}) challenges the transmission — re-examine.",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="MECHANISM_UNREGISTERED",
                    issue=f"registered mechanism contradicted by pack evidence (severity {max_severity})",
                    suggested_change="reconcile the claim's mechanism against the contradicting evidence",
                    severity="MEDIUM",
                )
            ],
        )

    return (
        "ACCEPT",
        0.8,
        "every claim maps to a registered transmission mechanism and no strong "
        "contradiction stands — the causal read is plausible.",
        [],
    )


# ------------------------------------------------------------------ Market
def _market(
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    state_diff = facet_slice.get("state_diff")
    historical = facet_slice.get("historical_percentile")
    percentile = historical.percentile if historical is not None else None

    if percentile is not None and percentile >= config.priced_in_percentile:
        return (
            "REFINE",
            0.7,
            f"the read sits at historical percentile {percentile} "
            f"(>= {config.priced_in_percentile}) — it is already reflected/priced.",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="ALREADY_PRICED_IN",
                    issue=f"historical percentile {percentile} at/above priced-in floor {config.priced_in_percentile}",
                    suggested_change="frame the read as confirmation, not a fresh edge; check for a differentiated angle",
                    severity="MEDIUM",
                )
            ],
        )
    if state_diff is not None and state_diff.changed is False:
        return (
            "REFINE",
            0.6,
            "state_diff shows no change vs the prior read — the directional call adds "
            "no new information (already priced in).",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="ALREADY_PRICED_IN",
                    issue="state_diff.changed is False — no new information vs prior",
                    suggested_change="identify what materially changed, or withdraw the directional call",
                    severity="LOW",
                )
            ],
        )
    return (
        "ACCEPT",
        0.7,
        "the read is not at a priced-in extreme and reflects a state change — it "
        "carries fresh information.",
        [],
    )


# ------------------------------------------------------------------ Risk
def _risk(
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    excluded = facet_slice.get("excluded_signals") or ()
    invalidation = assessment.invalidation_conditions or ()

    if not invalidation:
        return (
            "REFINE",
            0.8,
            "the assessment carries NO invalidation_conditions — the thesis is "
            "unfalsifiable (what would destroy it?).",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="NO_INVALIDATION_CONDITION",
                    issue="assessment.invalidation_conditions is empty",
                    suggested_change="state at least one falsification condition that would invalidate the thesis",
                    severity="MEDIUM",
                )
            ],
        )

    material = [
        s for s in excluded if (s.importance or 0.0) >= config.material_excluded_importance
    ]
    if material:
        names = ", ".join(s.signal_id for s in material)
        return (
            "REFINE",
            0.6,
            f"material signal(s) excluded ({names}) without a matching invalidation "
            f"condition — a hidden risk to the thesis.",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="NO_INVALIDATION_CONDITION",
                    issue=f"material excluded signal(s) [{names}] not covered by an invalidation condition",
                    suggested_change="add an invalidation condition covering the excluded material signal(s)",
                    severity="MEDIUM",
                )
            ],
        )
    return (
        "ACCEPT",
        0.75,
        "the thesis carries invalidation conditions and excludes no material signal "
        "left uncovered — its risk framing is honest.",
        [],
    )


# ------------------------------------------------------------------ Model
def _model(
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    pack_integrity = facet_slice.get("pack_integrity")
    domain_state = facet_slice.get("domain_state")
    data_quality = facet_slice.get("data_quality")
    integrity = domain_state.integrity if domain_state is not None else None
    outcome = pack_integrity.pack_outcome if pack_integrity is not None else None
    coverage = data_quality.coverage if data_quality is not None else None

    # An unmeasured/down integrity never satisfies the "healthy" path.
    if integrity is None or integrity in _DOWN_INTEGRITY:
        return (
            "REFINE",
            0.8,
            f"the underlying domain_state integrity is degraded ({integrity}) — the "
            f"model read is not trustworthy (MODEL_DEGRADING).",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="MODEL_DEGRADING",
                    issue=f"domain_state integrity is {integrity}",
                    suggested_change="refresh the underlying state or abstain until integrity recovers",
                    severity="MEDIUM",
                )
            ],
        )
    if outcome == "degraded":
        return (
            "REFINE",
            0.7,
            "pack_integrity reports a degraded pack outcome — the model inputs are "
            "degrading (MODEL_DEGRADING).",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="MODEL_DEGRADING",
                    issue="pack_integrity.pack_outcome == 'degraded'",
                    suggested_change="restore the degraded facets before relying on the model read",
                    severity="MEDIUM",
                )
            ],
        )
    if coverage is not None and coverage < config.min_model_coverage:
        return (
            "REFINE",
            0.65,
            f"data coverage {coverage} is below the model floor "
            f"{config.min_model_coverage} — the model read is degrading.",
            [
                _target(
                    config,
                    verdict_id,
                    issue_id="MODEL_DEGRADING",
                    issue=f"data coverage {coverage} below model floor {config.min_model_coverage}",
                    suggested_change="raise data coverage before trusting the model read",
                    severity="LOW",
                )
            ],
        )
    return (
        "ACCEPT",
        0.8,
        "domain_state integrity is healthy, the pack is not degraded, and coverage is "
        "sufficient — the model read is not degrading.",
        [],
    )


_LENS_EVALUATORS = {
    "EVIDENCE": _evidence,
    "CAUSALITY": _causality,
    "MARKET": _market,
    "RISK": _risk,
    "MODEL": _model,
}


def evaluate_lens(
    *,
    config: LensConfig,
    assessment: DomainAssessment,
    facet_slice: dict,
    registry: CausalMechanismRegistry,
    verdict_id: str,
) -> LensResult:
    """Dispatch to the lens's rule bundle (first-matching-rule-wins, pure)."""
    evaluator = _LENS_EVALUATORS.get(config.lens)
    if evaluator is None:  # pragma: no cover - LensConfig.lens is Literal-validated
        raise KeyError(f"no rule bundle for lens {config.lens!r}")
    return evaluator(config, assessment, facet_slice, registry, verdict_id)


__all__ = ["evaluate_lens", "LensResult"]
