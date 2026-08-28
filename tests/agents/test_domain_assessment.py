"""Phase 169 Plan 02 Task 2 + Plan 06 Task 2 — DomainAgent.assess() behavior proof.

Proves the net-new deterministic `assess(pack) -> DomainAssessment` path (AGV-10 / D-07):
- emits a real, non-empty, falsifiable claim set (NOT stubs),
- copies level/momentum from the typed pack (never recomputes),
- sources state_version from PackIdentity.state_version (D-10),
- threads pack.knowledge_time immutably (reproducible claim_ids; no datetime.now),
- maps a degraded pack to an explicit abstention outcome via the tier engine.

Two layers coexist:
- The fixture-based single-slug reference path (Plan 02) — the sample_domain_definition
  fixture drives the base's assess() against a synthetic inflation-shaped block.
- The Plan-06 12-slug sweep proof (bottom of file) — parameterized over ALL 12 real
  `agents/<slug>_domain_analyst/agent.py` migrated subclasses, each loading its REAL
  `domain_definition:` block from `registry/agent_profile/vm107.<slug>_domain_analyst.yaml`
  via DomainDefinition.from_profile, and asserting the minimum-falsifiable DomainAssessment
  set (non-empty claims, integrity_state set, state_version pass-through, no new counter,
  claim_id stability across a fixed (state_version, knowledge_time) rerun). This is where
  AGV-09/AGV-10 for all 12 is proven green against the migrated on-disk config subclasses.

The legacy `invoke()` surface is guarded by the existing
tests/agents/test_domain_analyst_contract.py (unchanged this plan).
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fingpt_core.contracts.assessment import (
    AbstentionOutcome,
    DomainAssessment,
    Horizon,
)
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

from core.agents.domain_agent import DomainAgent
from core.agents.domain_definition import DomainDefinition


class _RefInflationAgent(DomainAgent):
    """Fixture-only concrete subclass — the 12 on-disk subclasses land in Plan 169-06."""

    DOMAIN = "Inflation"
    DOMAIN_SLUG = "inflation"
    AGENT_ID = "vm107.inflation_domain_analyst"


def _agent(defn):
    return _RefInflationAgent(domain_definition=defn)


def test_assess_returns_domain_assessment(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert isinstance(out, DomainAssessment)
    assert out.domain == "Inflation"
    assert out.geography_id == "US"
    assert out.geography_type == "country"


def test_state_version_sourced_from_pack_identity(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert out.state_version == domain_evidence_pack.identity.state_version == "v128"
    assert out.manifest.state_version == "v128"
    for claim in out.claims:
        assert claim.state_version == "v128"


def test_level_and_momentum_copied_from_pack(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    # level copied verbatim from domain_state.score
    assert out.level == domain_evidence_pack.domain_state.score
    # momentum copied from state_diff.delta_score (within contract bounds)
    assert out.momentum == domain_evidence_pack.state_diff.delta_score


def test_claims_are_non_empty_and_falsifiable(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert len(out.claims) >= 1
    for claim in out.claims:
        assert claim.claim_id.startswith("clm_")
        assert claim.subject and claim.predicate and claim.object
        assert claim.invalidation_conditions  # falsifiable — never a bare stub
        assert claim.generated_by == "vm107.inflation_domain_analyst"
    # assessment-level falsifiers present
    assert out.invalidation_conditions


def test_current_state_classifier_labels_deterministically(
    evidence_pack_builder, sample_domain_definition, ref_knowledge_time
):
    # momentum <= -0.1 -> DISINFLATION
    pack = evidence_pack_builder(knowledge_time=ref_knowledge_time, level=0.4, momentum=-0.3)
    out = _agent(sample_domain_definition).assess(pack)
    # the classified state rides in the OBSERVATION claim object
    obs = [c for c in out.claims if c.claim_class.value == "OBSERVATION"][0]
    assert obs.object == "DISINFLATION"


def test_integrity_state_set_and_no_abstention_when_healthy(
    domain_evidence_pack, sample_domain_definition
):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert out.integrity_state == FacetIntegrity.NEUTRAL
    assert out.abstention_outcome is None


def test_degraded_pack_maps_to_abstention_via_tiers(
    degraded_evidence_pack, sample_domain_definition
):
    out = _agent(sample_domain_definition).assess(degraded_evidence_pack)
    assert out.abstention_outcome is not None
    # domain_state STALE -> STATE_STALE abstain code (ABSTAIN_BY_FACET)
    assert out.abstention_outcome == AbstentionOutcome.STATE_STALE
    assert out.integrity_state == FacetIntegrity.STALE


def test_claim_ids_reproducible_for_fixed_state_and_knowledge_time(
    evidence_pack_builder, sample_domain_definition, ref_knowledge_time
):
    a = _agent(sample_domain_definition)
    p1 = evidence_pack_builder(knowledge_time=ref_knowledge_time)
    p2 = evidence_pack_builder(knowledge_time=ref_knowledge_time)
    ids1 = [c.claim_id for c in a.assess(p1).claims]
    ids2 = [c.claim_id for c in a.assess(p2).claims]
    assert ids1 == ids2  # same (state_version, knowledge_time) -> identical ids


def test_knowledge_time_threaded_immutably(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert out.knowledge_time == domain_evidence_pack.knowledge_time
    assert out.manifest.knowledge_time == domain_evidence_pack.knowledge_time
    # deterministic (LLM-free) manifest — no wall-clock re-stamp
    assert out.manifest.execution_time == domain_evidence_pack.knowledge_time
    assert out.manifest.model == "deterministic"


def test_assessment_horizon_from_definition(domain_evidence_pack, sample_domain_definition):
    out = _agent(sample_domain_definition).assess(domain_evidence_pack)
    assert out.horizon == Horizon.NOWCAST


# ---------------------------------------------------------------------------
# Plan 06 Task 2 — 12-slug assess() sweep against the REAL domain_definition:
# blocks + the migrated on-disk config subclasses (AGV-09/AGV-10 for all 12).
# ---------------------------------------------------------------------------

# CONTEXT §A canonical 12 (mirrors test_domain_analyst_contract.DOMAIN_SLUGS).
DOMAIN_SLUGS = [
    "inflation",
    "growth",
    "labour",
    "housing",
    "credit",
    "monetary_policy",
    "fiscal",
    "external_sector",
    "manufacturing",
    "consumer",
    "financial_conditions",
    "commodities",
]

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_SWEEP_KNOWLEDGE_TIME = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def _class_name(slug: str) -> str:
    return "".join(part.title() for part in slug.split("_")) + "DomainAnalyst"


def _agent_class(slug: str):
    module = importlib.import_module(f"agents.{slug}_domain_analyst.agent")
    return getattr(module, _class_name(slug))


def _profile_path(slug: str) -> Path:
    return (
        _VM107_ROOT
        / "registry"
        / "agent_profile"
        / f"vm107.{slug}_domain_analyst.yaml"
    )


def _real_definition(slug: str) -> DomainDefinition:
    """Load the slug's REAL domain_definition: block from its profile manifest."""
    return DomainDefinition.from_profile(_profile_path(slug))


def _sweep_pack(
    slug: str,
    *,
    knowledge_time: datetime = _SWEEP_KNOWLEDGE_TIME,
    level: float | None = 0.42,
    momentum: float | None = 0.15,
) -> DomainEvidencePack:
    """A representative, healthy DomainEvidencePack keyed to `slug` (state_version v128)."""
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
        identity=PackIdentity(country="US", domain_slug=slug, state_version="v128"),
        domain_state=DomainStateFacet(
            state_version="v128",
            as_of=knowledge_time,
            label="reference-state",
            score=level,
            confidence=0.71,
            integrity=FacetIntegrity.NEUTRAL,
        ),
        state_diff=StateDiffFacet(
            changed=True,
            previous_label="prior",
            current_label="reference-state",
            delta_score=momentum,
            integrity=FacetIntegrity.NEUTRAL,
        ),
        knowledge_time=knowledge_time,
        pack_integrity=PackIntegrity(pack_outcome="success", facets=facets),
        top_contributors=(
            ContributorFacet(name="DriverA", contribution=-0.3, confidence=0.8),
            ContributorFacet(name="DriverB", contribution=0.5, confidence=0.9),
        ),
        top_signals=(
            SignalFacet(signal_id="SIG_LEAD", importance=0.9),
            SignalFacet(signal_id="SIG_LAG", importance=0.7),
        ),
    )


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_migrated_subclass_assess_emits_domain_assessment_from_real_block(slug):
    """Each migrated on-disk subclass, loading its REAL domain_definition: block,
    emits a falsifiable DomainAssessment with the minimum set — no recomputed state,
    no new state counter (AGV-09/AGV-10)."""
    defn = _real_definition(slug)
    Analyst = _agent_class(slug)
    assert issubclass(Analyst, DomainAgent)

    pack = _sweep_pack(slug)
    out = Analyst(domain_definition=defn).assess(pack)

    assert isinstance(out, DomainAssessment)
    # state facts COPIED from the pack — never recomputed
    assert out.level == pack.domain_state.score
    assert out.momentum == pack.state_diff.delta_score
    # no parallel counter — state_version passes straight through PackIdentity (D-10)
    assert out.state_version == pack.identity.state_version == "v128"
    assert out.manifest.state_version == "v128"
    # integrity_state is set (not None) from the pack
    assert out.integrity_state is not None
    assert out.integrity_state == pack.domain_state.integrity
    # knowledge_time threaded immutably; deterministic manifest (LLM-free)
    assert out.knowledge_time == pack.knowledge_time
    assert out.manifest.execution_time == pack.knowledge_time
    assert out.manifest.model == "deterministic"

    # non-empty, falsifiable claims from the REAL block's templates (not stubs)
    assert len(out.claims) >= 1
    for claim in out.claims:
        assert claim.claim_id.startswith("clm_")
        assert claim.subject and claim.predicate and claim.object
        assert claim.invalidation_conditions  # falsifiable
        assert claim.generated_by == Analyst.AGENT_ID
        assert claim.state_version == "v128"
    # assessment-level falsifiers present
    assert out.invalidation_conditions


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
def test_migrated_subclass_claim_ids_stable_across_rerun(slug):
    """claim_id is stable across a rerun of the same (state_version, knowledge_time) —
    deterministic + reproducible per slug (no wall-clock re-stamp)."""
    defn = _real_definition(slug)
    Analyst = _agent_class(slug)
    agent = Analyst(domain_definition=defn)

    p1 = _sweep_pack(slug)
    p2 = _sweep_pack(slug)
    ids1 = [c.claim_id for c in agent.assess(p1).claims]
    ids2 = [c.claim_id for c in agent.assess(p2).claims]
    assert ids1 == ids2
    assert ids1  # non-empty
