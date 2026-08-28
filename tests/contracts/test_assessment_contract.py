"""Phase 169-01 (D-01/D-02/D-10, AGV-10) — DomainAssessment contract tests.

Proves the shared `DomainAssessment` (+ its `Claim`, `Confidence`,
`ReproducibilityManifest` sub-models) enforce the falsifiability guarantees the whole
phase is built around:

1. A FULLY-POPULATED assessment carrying the minimum-falsifiable field set constructs.
2. `extra="forbid"` rejects an unknown key (ValidationError) — malformed input can't
   smuggle fields past the contract (ASVS V5 input validation).
3. The model is frozen — a landed assessment can't be mutated after the fact.
4. `claims` is a `tuple` (frozen-safe collection), not a list.
5. `state_version` accepts the same plain str a `PackIdentity.state_version` carries
   (D-10 — no parallel counter).

Host-clean: imports the shared `fingpt_core` contract (stdlib + pydantic) only — the same
import path VM107 uses at runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

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
from fingpt_core.contracts.evidence_pack import FacetIntegrity, PackIdentity

_KT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
_STATE_VERSION = "v128"


def _make_claim() -> Claim:
    cid = compute_claim_id(
        domain="inflation",
        geography="US",
        claim_class=ClaimClass.OBSERVATION,
        subject="core cpi",
        predicate="is",
        object="elevated",
        state_version=_STATE_VERSION,
        knowledge_time=_KT,
    )
    return Claim(
        claim_id=cid,
        claim_class=ClaimClass.OBSERVATION,
        subject="core cpi",
        predicate="is",
        object="elevated",
        horizon=Horizon.NOWCAST,
        confidence=0.82,
        evidence_refs=("ev:cpi:core:3m",),
        contradicting_evidence_refs=("ev:services:breadth",),
        assumptions=("shelter lag holds",),
        invalidation_conditions=("core 3m momentum < 40th pct",),
        generated_by="inflation.reasoning_rules.current_state",
        state_version=_STATE_VERSION,
    )


def _make_manifest() -> ReproducibilityManifest:
    return ReproducibilityManifest(
        agent_version="169.1",
        model="deterministic",
        prompt_version="1",
        state_version=_STATE_VERSION,
        feature_set_version="fs.1",
        knowledge_version="kv.1",
        tool_versions=("domain_engine@1",),
        evidence_ids=("ev:cpi:core:3m",),
        knowledge_time=_KT,
        execution_time=_KT,
    )


def _make_assessment(**overrides) -> DomainAssessment:
    kwargs = dict(
        domain="inflation",
        geography_id="US",
        geography_type="country",
        sector=None,
        state_version=_STATE_VERSION,
        horizon=Horizon.NOWCAST,
        level=0.6,
        momentum=-0.3,
        surprise=1.4,
        confidence=Confidence(
            data=0.8, state_model=0.75, interpretation=0.6, forecast=0.5, overall=0.71
        ),
        integrity_state=FacetIntegrity.NEUTRAL,
        claims=(_make_claim(),),
        invalidation_conditions=("services breadth normalises",),
        abstention_outcome=None,
        manifest=_make_manifest(),
        knowledge_time=_KT,
    )
    kwargs.update(overrides)
    return DomainAssessment(**kwargs)


def test_fully_populated_assessment_constructs():
    """The minimum-falsifiable field set constructs and carries its parts."""
    a = _make_assessment()
    assert a.domain == "inflation"
    assert a.horizon is Horizon.NOWCAST
    # separate level/momentum/surprise — never collapsed
    assert a.level == 0.6 and a.momentum == -0.3 and a.surprise == 1.4
    # decomposed confidence
    assert a.confidence.data == 0.8 and a.confidence.overall == 0.71
    assert a.manifest.knowledge_time == _KT
    assert a.assessment_schema_version == "1.0"


def test_claims_is_a_tuple():
    """The claims collection is a frozen-safe tuple, not a list."""
    a = _make_assessment()
    assert isinstance(a.claims, tuple)
    assert isinstance(a.claims[0], Claim)


def test_extra_forbid_rejects_unknown_key():
    """An unknown kwarg is rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        _make_assessment(unexpected_field="boom")


def test_assessment_is_frozen():
    """A landed assessment cannot be mutated."""
    a = _make_assessment()
    with pytest.raises(ValidationError):
        a.domain = "growth"


def test_claim_is_frozen_and_forbids_extra():
    """The Claim sub-model is frozen + extra='forbid' too."""
    c = _make_claim()
    with pytest.raises(ValidationError):
        c.subject = "headline cpi"
    with pytest.raises(ValidationError):
        Claim(
            claim_id=c.claim_id,
            claim_class=ClaimClass.OBSERVATION,
            subject="x",
            predicate="y",
            object="z",
            horizon=Horizon.NOWCAST,
            confidence=0.5,
            generated_by="rule",
            state_version=_STATE_VERSION,
            bogus="nope",
        )


def test_state_version_mirrors_pack_identity(  ):
    """state_version accepts the exact str a PackIdentity.state_version carries (D-10)."""
    identity = PackIdentity(country="US", domain_slug="inflation", state_version=_STATE_VERSION)
    a = _make_assessment(state_version=identity.state_version)
    assert a.state_version == identity.state_version
    assert a.manifest.state_version == identity.state_version


def test_abstention_outcome_optional_and_typed():
    """abstention_outcome is optional and, when set, a typed AbstentionOutcome."""
    a = _make_assessment(abstention_outcome=AbstentionOutcome.STATE_STALE)
    assert a.abstention_outcome is AbstentionOutcome.STATE_STALE
    assert _make_assessment().abstention_outcome is None
