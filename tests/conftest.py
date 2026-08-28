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

from fingpt_core.contracts.evidence_pack import (
    ContributorFacet,
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
