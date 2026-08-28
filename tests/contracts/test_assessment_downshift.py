"""Phase 169-03 (D-01 / D-03, AGV-10) — the ⊇ projection LOCK.

Locks the `DomainAssessment ⊇ SpecialistResponse` relationship as an explicit, tested
projection (`to_specialist_response`). This is the test AGV-10 requires: it proves the
downshift covers EVERY `SpecialistResponse` field from a `DomainAssessment` field (no field
left at its default when the source carries data) AND that the frozen `extra="forbid"` target
contract is neither touched nor weakened by the adapter.

Coverage strategy: build a fully-populated DomainAssessment (real claims with evidence_refs,
assessment-level invalidation_conditions, a sector, a typed abstention_outcome), project it,
then assert each of the seven SpecialistResponse fields is derived and non-trivial. A second
group re-asserts `extra="forbid"` still rejects an unknown key on the target itself.

Host-clean: imports the shared `fingpt_core` contract (stdlib + pydantic) + the VM107-local
target + adapter — exactly the runtime import surface.
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
from fingpt_core.contracts.evidence_pack import FacetIntegrity

from contracts.economic_intelligence.assessment_downshift import to_specialist_response
from contracts.economic_intelligence.specialist_response import SpecialistResponse

_KT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
_STATE_VERSION = "v128"

# The exact field set the projection must cover (specialist_response.py). schema_version is
# intentionally excluded from the coverage assertion — it stays at the target's default "1"
# (the enriched assessment_schema_version is NOT projected onto the untouched contract).
_COVERED_FIELDS = ("answer", "confidence", "citations", "evidence", "limitations", "related_entities")


def _make_claim(subject: str, ref: str) -> Claim:
    cid = compute_claim_id(
        domain="inflation",
        geography="US",
        claim_class=ClaimClass.OBSERVATION,
        subject=subject,
        predicate="is",
        object="elevated",
        state_version=_STATE_VERSION,
        knowledge_time=_KT,
    )
    return Claim(
        claim_id=cid,
        claim_class=ClaimClass.OBSERVATION,
        subject=subject,
        predicate="is",
        object="elevated",
        horizon=Horizon.NOWCAST,
        confidence=0.82,
        evidence_refs=(ref,),
        contradicting_evidence_refs=("ev:services:breadth",),
        assumptions=("shelter lag holds",),
        invalidation_conditions=("core 3m momentum < 40th pct",),
        generated_by="inflation.reasoning_rules.current_state",
        state_version=_STATE_VERSION,
    )


def _make_assessment(**overrides) -> DomainAssessment:
    kwargs = dict(
        domain="inflation",
        geography_id="US",
        geography_type="country",
        sector="services",
        state_version=_STATE_VERSION,
        horizon=Horizon.NOWCAST,
        level=0.6,
        momentum=-0.3,
        surprise=1.4,
        confidence=Confidence(
            data=0.8, state_model=0.75, interpretation=0.6, forecast=0.5, overall=0.71
        ),
        integrity_state=FacetIntegrity.NEUTRAL,
        claims=(
            _make_claim("core cpi", "ev:cpi:core:3m"),
            _make_claim("core pce", "ev:pce:core:3m"),
        ),
        invalidation_conditions=("services breadth normalises",),
        abstention_outcome=AbstentionOutcome.ASSESSMENT_UNCERTAIN,
        manifest=ReproducibilityManifest(
            agent_version="169.3",
            model="deterministic",
            prompt_version="1",
            state_version=_STATE_VERSION,
            feature_set_version="fs.1",
            knowledge_version="kv.1",
            tool_versions=("domain_engine@1",),
            evidence_ids=("ev:cpi:core:3m",),
            knowledge_time=_KT,
            execution_time=_KT,
        ),
        knowledge_time=_KT,
    )
    kwargs.update(overrides)
    return DomainAssessment(**kwargs)


# --------------------------------------------------------------------------- projection type


def test_returns_specialist_response_instance():
    """to_specialist_response(assessment) returns a valid SpecialistResponse."""
    resp = to_specialist_response(_make_assessment())
    assert isinstance(resp, SpecialistResponse)


# --------------------------------------------------------------------------- ⊇ field coverage


def test_every_specialist_response_field_is_covered():
    """No SpecialistResponse field is left default when the assessment carries data (⊇)."""
    a = _make_assessment()
    resp = to_specialist_response(a)

    # answer — non-empty deterministic summary carrying the level/momentum/horizon read.
    assert resp.answer  # min_length=1 satisfied
    assert a.domain in resp.answer
    assert a.horizon.value in resp.answer

    # confidence — the decomposed overall roll-up, byte-for-byte.
    assert resp.confidence == a.confidence.overall

    # citations — flattened, de-duplicated claim evidence_refs; non-empty since claims have refs.
    assert resp.citations == ["ev:cpi:core:3m", "ev:pce:core:3m"]

    # evidence — one open dict per claim, carrying the claim's identity + refs.
    assert len(resp.evidence) == len(a.claims)
    assert resp.evidence[0]["claim_id"] == a.claims[0].claim_id
    assert resp.evidence[0]["subject"] == a.claims[0].subject
    assert resp.evidence[0]["evidence_refs"] == list(a.claims[0].evidence_refs)

    # limitations — assessment invalidation_conditions + the typed abstention caveat.
    assert "services breadth normalises" in resp.limitations
    assert any("assessment_uncertain" in lim.lower() for lim in resp.limitations)

    # related_entities — domain + geography(type:id) + optional sector cross-refs.
    assert "domain:inflation" in resp.related_entities
    assert "geography:country:US" in resp.related_entities
    assert "sector:services" in resp.related_entities

    # every covered field is non-trivially populated (no empty/default when source has data).
    for field in _COVERED_FIELDS:
        value = getattr(resp, field)
        assert value not in (None, "", [], {}), f"{field} left trivially default"


def test_sector_absent_drops_only_the_sector_ref():
    """A sector-less assessment still covers domain/geography; sector ref simply absent."""
    resp = to_specialist_response(_make_assessment(sector=None))
    assert "domain:inflation" in resp.related_entities
    assert "geography:country:US" in resp.related_entities
    assert not any(r.startswith("sector:") for r in resp.related_entities)


def test_no_abstention_omits_the_abstention_caveat():
    """With no abstention, limitations carry only the invalidation conditions."""
    resp = to_specialist_response(_make_assessment(abstention_outcome=None))
    assert resp.limitations == ["services breadth normalises"]
    assert not any("abstain" in lim.lower() for lim in resp.limitations)


def test_schema_version_stays_target_default():
    """The adapter does NOT project assessment_schema_version onto the target's schema_version."""
    resp = to_specialist_response(_make_assessment())
    assert resp.schema_version == "1"  # SpecialistResponse default, untouched


# --------------------------------------------------------------------------- extra="forbid" lock


def test_projection_output_is_frozen():
    """The projected SpecialistResponse is frozen — it can't be mutated after the fact."""
    resp = to_specialist_response(_make_assessment())
    with pytest.raises(ValidationError):
        resp.answer = "tampered"


def test_extra_forbid_still_rejects_unknown_key():
    """The frozen extra='forbid' target still rejects an unknown key (adapter didn't weaken it)."""
    a = _make_assessment()
    resp = to_specialist_response(a)
    with pytest.raises(ValidationError):
        SpecialistResponse(
            answer=resp.answer,
            confidence=resp.confidence,
            citations=resp.citations,
            evidence=resp.evidence,
            limitations=resp.limitations,
            related_entities=resp.related_entities,
            smuggled_field="boom",
        )
