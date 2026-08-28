"""VM107 tests/ shared fixtures — Phase 169 Plan 02 additions.

Provides fixture-based reference inputs for the generic DomainAgent base
(core/agents/domain_agent.py) so its net-new `assess(pack) -> DomainAssessment`
path can be exercised without touching the 12 on-disk profile blocks (those
land in Plan 169-04). Fixtures are uniquely named (`domain_evidence_pack`,
`sample_domain_definition`) to avoid collision with the per-package conftests.

Path setup is handled by the VM107 root conftest.py; nothing added here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fingpt_core.contracts.assessment import (
    Claim,
    ClaimClass,
    Confidence,
    DomainAssessment,
    Horizon,
    ReproducibilityManifest,
    compute_claim_id,
)
from fingpt_core.contracts.evidence_pack import (
    ContradictionFacet,
    ContributorFacet,
    DataQualityFacet,
    DomainEvidencePack,
    DomainStateFacet,
    FacetIntegrity,
    FacetIntegrityRecord,
    FacetTier,
    PackIdentity,
    PackIntegrity,
    SignalFacet,
    StateDiffFacet,
)

_REF_KNOWLEDGE_TIME = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def ref_knowledge_time() -> datetime:
    """A fixed, immutable knowledge_time for reproducible assessments."""
    return _REF_KNOWLEDGE_TIME


@pytest.fixture
def sample_domain_definition():
    """A minimal but real DomainDefinition (inflation-shaped) for the reference path."""
    from core.agents.domain_definition import DomainDefinition

    return DomainDefinition.from_profile(
        {
            "version": "1.0.0",
            "knowledge_version": "kb-2026.08",
            "indicators": ["CPIAUCSL", "PCEPI", "ISM_PRICES"],
            "signal_roles": {"lead": ["ISM_PRICES"], "lag": ["CPIAUCSL"]},
            "horizons": ["NOWCAST", "NEAR_TERM"],
            "calendar": "monthly-cpi",
            "materiality_thresholds": {"level": 0.5, "momentum": 0.3},
            "evaluation": {"correctness_kpi": "engine-lock respected = 1.0"},
            "reasoning_rules": {
                "default_state": "INDETERMINATE",
                "state_rules": [
                    {"state": "DISINFLATION", "momentum_max": -0.1},
                    {"state": "STICKY_SERVICES", "level_min": 0.2, "momentum_min": -0.1},
                ],
                "claim_templates": [
                    {
                        "claim_class": "OBSERVATION",
                        "subject": "{domain} in {geography}",
                        "predicate": "is currently classified as",
                        "object": "{state}",
                        "horizon": "NOWCAST",
                        "invalidation_conditions": ["current_state classifier changes label"],
                        "assumptions": ["typed state read is fresh"],
                    },
                    {
                        "claim_class": "INTERPRETATION",
                        "subject": "{domain} momentum",
                        "predicate": "reads",
                        "object": "{momentum}",
                        "horizon": "NEAR_TERM",
                        "invalidation_conditions": ["momentum sign flips on next release"],
                    },
                ],
                "invalidation_conditions": ["a new DomainState snapshot supersedes state_version"],
            },
        }
    )


def _build_pack(
    *,
    knowledge_time: datetime,
    pack_outcome: str = "success",
    state_integrity: FacetIntegrity = FacetIntegrity.NEUTRAL,
    state_diff_integrity: FacetIntegrity = FacetIntegrity.NEUTRAL,
    level: float | None = 0.42,
    momentum: float | None = 0.15,
) -> DomainEvidencePack:
    facets = (
        FacetIntegrityRecord(
            facet="domain_state", tier=FacetTier.REQUIRED, integrity=state_integrity, reason=None
        ),
        FacetIntegrityRecord(
            facet="state_diff", tier=FacetTier.REQUIRED, integrity=state_diff_integrity, reason=None
        ),
        FacetIntegrityRecord(
            facet="contribution", tier=FacetTier.IMPORTANT, integrity=FacetIntegrity.NEUTRAL, reason=None
        ),
    )
    return DomainEvidencePack(
        identity=PackIdentity(country="US", domain_slug="inflation", state_version="v128"),
        domain_state=DomainStateFacet(
            state_version="v128",
            as_of=knowledge_time,
            label="Elevated/Moderating",
            score=level,
            confidence=0.71,
            integrity=state_integrity,
        ),
        state_diff=StateDiffFacet(
            changed=True,
            previous_label="Elevated",
            current_label="Elevated/Moderating",
            delta_score=momentum,
            integrity=state_diff_integrity,
        ),
        knowledge_time=knowledge_time,
        pack_integrity=PackIntegrity(pack_outcome=pack_outcome, facets=facets),
        top_contributors=(
            ContributorFacet(name="Goods", contribution=-0.3, confidence=0.8),
            ContributorFacet(name="Shelter", contribution=0.5, confidence=0.9),
        ),
        top_signals=(
            SignalFacet(signal_id="CPIAUCSL", importance=0.9),
            SignalFacet(signal_id="PCEPI", importance=0.7),
        ),
    )


@pytest.fixture
def domain_evidence_pack(ref_knowledge_time):
    """A healthy (pack_outcome='success') reference DomainEvidencePack."""
    return _build_pack(knowledge_time=ref_knowledge_time)


@pytest.fixture
def degraded_evidence_pack(ref_knowledge_time):
    """A degraded pack: domain_state REQUIRED facet is STALE -> agent must abstain."""
    return _build_pack(
        knowledge_time=ref_knowledge_time,
        pack_outcome="degraded",
        state_integrity=FacetIntegrity.STALE,
    )


@pytest.fixture
def evidence_pack_builder():
    """Expose the pack builder for tests needing custom level/momentum/integrity."""
    return _build_pack


# =============================================================================
# Phase 170 Plan 01 — shared SC#2 critic-panel fixtures.
#
# These are the read-only INPUT contracts every downstream critic test consumes
# (Pitfall 4): DomainAssessment / Claim / DomainEvidencePack are imported from
# fingpt_core and NEVER redefined here. A bare-correlation INTERPRETATION claim
# (no seeded transmission mechanism) is the SC#2 Causality-REJECT input; a
# supported claim (matches the verified inflation domain_definition seed) is the
# ACCEPT path.
# =============================================================================

_CRITIC_STATE_VERSION = "v128"


def _build_confidence(overall: float = 0.68) -> Confidence:
    """Decomposed confidence — data vs interpretation never collapsed (12 §6)."""
    return Confidence(
        data=0.70, state_model=0.72, interpretation=0.60, forecast=0.55, overall=overall
    )


def _build_manifest(knowledge_time: datetime) -> ReproducibilityManifest:
    """Deterministic (LLM-free) reproducibility manifest for the reference path."""
    return ReproducibilityManifest(
        agent_version="test-fixture-1.0.0",
        model="deterministic",
        prompt_version="test-prompt-1",
        state_version=_CRITIC_STATE_VERSION,
        feature_set_version="fs-1",
        knowledge_version="kb-2026.08",
        knowledge_time=knowledge_time,
        execution_time=knowledge_time,
    )


def _build_claim(
    *,
    claim_class: ClaimClass,
    subject: str,
    predicate: str,
    object_: str,
    knowledge_time: datetime,
    horizon: Horizon = Horizon.NEAR_TERM,
    confidence: float = 0.60,
) -> Claim:
    """Build a first-class Claim with a real deterministic claim_id (D-08)."""
    claim_id = compute_claim_id(
        domain="inflation",
        geography="US",
        claim_class=claim_class,
        subject=subject,
        predicate=predicate,
        object=object_,
        state_version=_CRITIC_STATE_VERSION,
        knowledge_time=knowledge_time,
    )
    return Claim(
        claim_id=claim_id,
        claim_class=claim_class,
        subject=subject,
        predicate=predicate,
        object=object_,
        horizon=horizon,
        confidence=confidence,
        generated_by="test-fixture",
        state_version=_CRITIC_STATE_VERSION,
    )


def _build_assessment(
    *,
    claim: Claim,
    knowledge_time: datetime,
    integrity_state: FacetIntegrity = FacetIntegrity.NEUTRAL,
) -> DomainAssessment:
    """Wrap a single claim in a well-formed DomainAssessment (no mocks — real typed obj)."""
    return DomainAssessment(
        domain="inflation",
        geography_id="US",
        geography_type="country",
        state_version=_CRITIC_STATE_VERSION,
        horizon=Horizon.NEAR_TERM,
        level=0.42,
        momentum=0.15,
        confidence=_build_confidence(),
        integrity_state=integrity_state,
        claims=(claim,),
        invalidation_conditions=(
            "a new DomainState snapshot supersedes state_version",
        ),
        manifest=_build_manifest(knowledge_time),
        knowledge_time=knowledge_time,
    )


@pytest.fixture
def bare_correlation_assessment(ref_knowledge_time) -> DomainAssessment:
    """SC#2 input — a directional 'signal' INTERPRETATION claim whose
    (domain, claim_class, subject/predicate) matches NO seeded transmission
    mechanism ('gold_open_interest' -> 'signals' -> inflation). This is the
    Causality-REJECT case (Constitution 11)."""
    claim = _build_claim(
        claim_class=ClaimClass.INTERPRETATION,
        subject="gold_open_interest",
        predicate="signals",
        object_="the elevated inflation reading",
        knowledge_time=ref_knowledge_time,
    )
    return _build_assessment(claim=claim, knowledge_time=ref_knowledge_time)


@pytest.fixture
def supported_assessment(ref_knowledge_time) -> DomainAssessment:
    """ACCEPT-path input — an INTERPRETATION claim whose key matches the verified
    inflation domain_definition seed ('core services ex-shelter' is the dominant
    driver of the inflation reading)."""
    claim = _build_claim(
        claim_class=ClaimClass.INTERPRETATION,
        subject="core services ex-shelter",
        predicate="is the dominant driver of",
        object_="the elevated inflation reading",
        knowledge_time=ref_knowledge_time,
    )
    return _build_assessment(claim=claim, knowledge_time=ref_knowledge_time)


@pytest.fixture
def minimal_evidence_pack(ref_knowledge_time) -> DomainEvidencePack:
    """A fully-populated pack so EVERY lens has a real facet slice to read (no mocks):
    domain_state, state_diff, top_contributors, top_signals, excluded_signals,
    contradictions, data_quality, pack_integrity all non-empty."""
    facets = (
        FacetIntegrityRecord(
            facet="domain_state", tier=FacetTier.REQUIRED, integrity=FacetIntegrity.NEUTRAL, reason=None
        ),
        FacetIntegrityRecord(
            facet="state_diff", tier=FacetTier.REQUIRED, integrity=FacetIntegrity.NEUTRAL, reason=None
        ),
        FacetIntegrityRecord(
            facet="contribution", tier=FacetTier.IMPORTANT, integrity=FacetIntegrity.NEUTRAL, reason=None
        ),
    )
    return DomainEvidencePack(
        identity=PackIdentity(country="US", domain_slug="inflation", state_version="v128"),
        domain_state=DomainStateFacet(
            state_version="v128",
            as_of=ref_knowledge_time,
            label="Elevated/Moderating",
            score=0.42,
            confidence=0.71,
            integrity=FacetIntegrity.NEUTRAL,
        ),
        state_diff=StateDiffFacet(
            changed=True,
            previous_label="Elevated",
            current_label="Elevated/Moderating",
            delta_score=0.15,
            integrity=FacetIntegrity.NEUTRAL,
        ),
        knowledge_time=ref_knowledge_time,
        pack_integrity=PackIntegrity(pack_outcome="success", facets=facets),
        top_contributors=(
            ContributorFacet(name="Core services ex-shelter", contribution=0.5, confidence=0.9),
            ContributorFacet(name="Goods", contribution=-0.3, confidence=0.8),
        ),
        top_signals=(
            SignalFacet(signal_id="core_services_ex_shelter_cpi", importance=0.9),
            SignalFacet(signal_id="wage_growth_eci", importance=0.7),
        ),
        excluded_signals=(
            SignalFacet(
                signal_id="gold_open_interest",
                importance=0.2,
                excluded_reason="no registered transmission mechanism to inflation",
            ),
        ),
        contradictions=(
            ContradictionFacet(
                claim_a="shelter_cpi still elevated",
                claim_b="observed market rents rolling over",
                severity=0.4,
            ),
        ),
        data_quality=DataQualityFacet(
            coverage=0.95, completeness=0.90, notes=("ISM_PRICES latest print T-2",)
        ),
    )
