"""Phase 170 Plan 04 Task 2 (D-04 / D-05) — the thin specialized-critic panel runner.

A NEW ADDITIVE SIBLING caller (mirror the SHAPE of
`refinement_orchestrator/main_loop.py` — a caller of a deterministic pre-critic
gate + `CriticVerdict`/`RefinementTarget` contracts). It does NOT edit that mature
strategy loop, does NOT touch `strategy_refinement_critic`, and does NOT call the
strategy-shaped critic wrapper (`invocation`, L810, StrategySpec/BacktestResult-
shaped) — the fragile-tree floor (D-04 / D-07).

Pitfall 2 (HIGH): the panel NEVER imports or calls the strategy backtest
veto/acceptance-floor gates (which take a `BacktestResult`) on a
`DomainAssessment` — those read backtest metrics and would raise / misbehave.
"Reuse" = reuse the PATTERN (a deterministic pre-critic gate) + the CONTRACTS,
not a literal call. Instead the panel short-circuits DOMAIN-NATIVE on what the
producer/pack already declined:
    assessment.abstention_outcome is not None
      OR pack.domain_state.integrity in _DOWN_INTEGRITY (STALE/UNAVAILABLE/...)
-> surface a REJECT/abstain verdict WITHOUT running the lenses (the pack declined).

Otherwise it fans the five `SpecializedCritic` lenses over the SAME
(assessment, pack), collects the five `CriticVerdict`s, and reduces them with the
pure reject-ceiling `aggregate_panel` (Task 1). Transformation-pure: the input
assessment is never mutated and the panel never approves-with-rewrite (05, D-05).
"""
from __future__ import annotations

import hashlib

# READ-ONLY input contracts (produced by 168/169; NEVER redefine — Pitfall 4).
from fingpt_core.contracts.assessment import DomainAssessment
from fingpt_core.contracts.evidence_pack import DomainEvidencePack, FacetIntegrity

# VM107-local OUTPUT contracts (D-06).
from core.contracts.schemas import CanonicalIssueId, CriticVerdict, RefinementTarget

from core.agents.specialized_critic.aggregate import aggregate_panel
from core.agents.specialized_critic.base import SpecializedCritic
from core.agents.specialized_critic.lens_config import LensConfig, default_lens_configs

# Integrity states that mark the underlying domain_state as "down" (mirror
# `core/agents/domain_agent.py` _DOWN_INTEGRITY — Unknown/failure, NOT a measured NEUTRAL).
_DOWN_INTEGRITY: frozenset[FacetIntegrity] = frozenset(
    {
        FacetIntegrity.UNKNOWN,
        FacetIntegrity.STALE,
        FacetIntegrity.UNAVAILABLE,
        FacetIntegrity.INSUFFICIENT_HISTORY,
        FacetIntegrity.PROVIDER_FAILURE,
    }
)


def check_domain_vetoes(
    assessment: DomainAssessment, pack: DomainEvidencePack
) -> str | None:
    """Pure DOMAIN-NATIVE short-circuit (NOT the strategy backtest veto set).

    Returns a human-readable reason string when the producer/pack has ALREADY
    declined the read (so running the lenses adds nothing but risk), else None.
    No IO, no LLM, no wall-clock — a first-match gate mirroring the strategy
    pre-critic gate's SHAPE, over domain-native signals only.
    """
    if assessment.abstention_outcome is not None:
        return (
            f"producer abstained (abstention_outcome="
            f"{getattr(assessment.abstention_outcome, 'value', assessment.abstention_outcome)}) "
            f"— no assertable claim to critique"
        )
    domain_state = getattr(pack, "domain_state", None)
    integrity = getattr(domain_state, "integrity", None) if domain_state is not None else None
    if integrity is not None and integrity in _DOWN_INTEGRITY:
        return (
            f"pack domain_state integrity is degraded ("
            f"{getattr(integrity, 'value', integrity)}) — the evidence base is not "
            f"trustworthy enough to accept the read"
        )
    return None


def _short_circuit_verdict(assessment: DomainAssessment, reason: str) -> CriticVerdict:
    """Build the domain-native REJECT/abstain verdict (no lenses run).

    A real, fully-populated `CriticVerdict` (Pitfall 6) citing the degraded
    integrity / abstention as a MODEL_DEGRADING RefinementTarget — deterministic,
    reproducible, transformation-pure (the assessment is read, never mutated).
    """
    snapshot_hash = hashlib.sha256(
        f"panel-shortcircuit|{assessment.state_version}|{reason}".encode("utf-8")
    ).hexdigest()
    verdict_id = f"scv-panel-abstain-{snapshot_hash[:16]}"
    target = RefinementTarget(
        scope="DOMAIN_ASSESSMENT",
        canonical_issue_id=CanonicalIssueId.MODEL_DEGRADING,
        target_field="integrity_state",
        issue=f"panel short-circuit: {reason}",
        issue_type="MODEL",
        severity="HIGH",
        suggested_change="restore the degraded state / lift the abstention before re-running the panel",
        source_critic_verdict_id=verdict_id,
    )
    return CriticVerdict(
        verdict="REJECT",
        confidence=0.9,
        refinement_targets=[target],
        failure_modes=[CanonicalIssueId.MODEL_DEGRADING.value],
        rationale=(
            f"panel REJECT (domain-native short-circuit) — {reason}; the five lenses "
            f"were not run because the producer/pack already declined the read."
        ),
        loaded_skills=[],
        source_critic_verdict_id=verdict_id,
        registry_snapshot_hash=snapshot_hash,
    )


def run_panel(
    assessment: DomainAssessment,
    pack: DomainEvidencePack,
    lens_configs: "dict[str, LensConfig] | None" = None,
    *,
    registry=None,
) -> CriticVerdict:
    """Fan the five `SpecializedCritic` lenses over one (assessment, pack) -> ONE verdict.

    1. DOMAIN-NATIVE short-circuit FIRST (`check_domain_vetoes`): if the producer
       abstained or the pack's domain_state integrity is degraded, surface a
       REJECT/abstain verdict WITHOUT running the lenses.
    2. Otherwise instantiate the five lenses from their configs
       (`default_lens_configs()` unless overridden), call `critique(assessment,
       pack)` on each, collect the five `CriticVerdict`s.
    3. Reduce via the pure reject-ceiling `aggregate_panel` (Task 1).

    Pure: the input `assessment` is never mutated (transformation-purity, D-05).
    """
    reason = check_domain_vetoes(assessment, pack)
    if reason is not None:
        return _short_circuit_verdict(assessment, reason)

    configs = lens_configs if lens_configs is not None else default_lens_configs()

    verdicts: list[CriticVerdict] = []
    for _lens_name, config in configs.items():
        critic = SpecializedCritic(lens_config=config, registry=registry)
        verdicts.append(critic.critique(assessment, pack))

    return aggregate_panel(verdicts)


__all__ = ["run_panel", "check_domain_vetoes"]
