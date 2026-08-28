"""Phase 169 Plan 02 Task 2 — DomainAgent.assess() behavior proof (fixture-based).

Proves the net-new deterministic `assess(pack) -> DomainAssessment` path (AGV-10 / D-07):
- emits a real, non-empty, falsifiable claim set (NOT stubs),
- copies level/momentum from the typed pack (never recomputes),
- sources state_version from PackIdentity.state_version (D-10),
- threads pack.knowledge_time immutably (reproducible claim_ids; no datetime.now),
- maps a degraded pack to an explicit abstention outcome via the tier engine.

Single-slug reference path only — parameterization over all 12 slugs against REAL
profile blocks lands in Plan 169-06. The legacy `invoke()` surface is guarded by the
existing tests/agents/test_domain_analyst_contract.py (unchanged this plan).
"""
from __future__ import annotations

from fingpt_core.contracts.assessment import (
    AbstentionOutcome,
    DomainAssessment,
    Horizon,
)
from fingpt_core.contracts.evidence_pack import FacetIntegrity

from core.agents.domain_agent import DomainAgent


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
