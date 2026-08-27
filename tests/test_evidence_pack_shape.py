"""Phase 168 Plan 05 Task 2 — healthy-fixture DomainEvidencePack shape.

Proves the reuse/typed facet composers (domain_state / state_diff / contribution
/ contradiction) compose a FULLY-POPULATED ``DomainEvidencePack`` in the fixed
ASSEMBLY_ORDER via typed seams (G10):

  * a healthy assemble yields pack_outcome "success" with domain_state,
    previous_state, state_diff, top_contributors, contradictions all populated,
  * the domain_state composer reaches its data through ``get_domain_state``
    (the typed VM102 client method — never a raw store),
  * the contribution facet flags a latest-only read served for a PAST as-of
    (Constitution 18 look-ahead honesty),
  * a contradiction (ENRICHMENT) engine failure OMITS the facet + records a
    reason — the pack is emitted, never raised.

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). Facet
data sources are injected FAKE seams — no live VM102 / Postgres.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from fingpt_core.contracts.evidence_pack import (
    ContradictionFacet,
    ContributorFacet,
    DomainEvidencePack,
    DomainStateFacet,
    StateDiffFacet,
)

from core.evidence import assembler as A
from core.evidence.facets import domain_state as ds_mod

_NOW = datetime.now(timezone.utc)
_PAST = _NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# Fake typed seams (stand in for the VM102 client path / ContradictionEngine)
# ---------------------------------------------------------------------------


class _FakeDomainStateReader:
    """Returns a healthy current+previous {status,data,meta} envelope (168-02 shape)."""

    def __init__(self):
        self.calls: list[dict] = []

    def get_domain_state(self, country, domain_slug, *, knowledge_time=None, previous=False):
        self.calls.append(
            {"country": country, "domain_slug": domain_slug, "knowledge_time": knowledge_time, "previous": previous}
        )
        return {
            "status": "ok",
            "data": {
                "current": {"label": "Stable", "score": 0.1, "confidence": 0.8},
                "previous": {"label": "Easing", "score": -0.1, "confidence": 0.7} if previous else None,
            },
            "meta": {"state_version": "US:monetary_policy:v5", "latest_only": False},
        }


class _FakeContributionReader:
    def contribution(self, country, domain_slug, *, knowledge_time=None):
        return [
            {"name": "US_CORE_CPI", "contribution": 0.42, "confidence": 0.7},
            {"name": "US_UNEMPLOYMENT", "contribution": -0.18, "confidence": 0.6},
        ]


class _FakeContradictionEngine:
    def detect_divergence(self, indicator_id, predicted_per_asset, actual_per_asset, sigma_historical):
        return {"EURUSD": 3.0}

    def grade_severity(self, divergence_sigma_per_asset, active_beliefs):
        return {"severity": "elevated"}


class _RaisingContradictionEngine:
    def detect_divergence(self, *a, **k):
        raise RuntimeError("contradiction postgres down")

    def grade_severity(self, *a, **k):
        raise RuntimeError("contradiction postgres down")


_CONTRADICTION_INPUTS = {
    "indicator_id": "CPIAUCSL",
    "predicted_per_asset": {"EURUSD": 1.0},
    "actual_per_asset": {"EURUSD": 1.6},
    "sigma_historical": {"EURUSD": 0.2},
    "active_beliefs": [],
}


def _healthy_deps(**overrides) -> A.FacetDeps:
    deps = A.FacetDeps(
        domain_state_reader=_FakeDomainStateReader(),
        contribution_reader=_FakeContributionReader(),
        contradiction_engine=_FakeContradictionEngine(),
        contradiction_inputs=_CONTRADICTION_INPUTS,
    )
    for k, v in overrides.items():
        setattr(deps, k, v)
    return deps


def _req(knowledge_time=_NOW) -> A.AssemblyRequest:
    return A.AssemblyRequest(country="US", domain_slug="monetary_policy", knowledge_time=knowledge_time)


def _records(pack: DomainEvidencePack) -> dict:
    return {f.facet: f for f in pack.pack_integrity.facets}


# ---------------------------------------------------------------------------
# Healthy full shape
# ---------------------------------------------------------------------------


def test_healthy_assemble_yields_full_populated_pack_in_fixed_order():
    pack = A.EvidencePackAssembler().assemble(_req(), deps=_healthy_deps())
    assert isinstance(pack, DomainEvidencePack)
    assert pack.pack_integrity.pack_outcome == "success"

    # REQUIRED + reuse facets populated
    assert isinstance(pack.domain_state, DomainStateFacet)
    assert pack.domain_state.label == "Stable"
    assert isinstance(pack.previous_state, DomainStateFacet)
    assert pack.previous_state.label == "Easing"
    assert isinstance(pack.state_diff, StateDiffFacet)
    assert pack.state_diff.changed is True
    assert len(pack.top_contributors) == 2
    assert all(isinstance(c, ContributorFacet) for c in pack.top_contributors)
    assert len(pack.contradictions) >= 1
    assert all(isinstance(c, ContradictionFacet) for c in pack.contradictions)

    # fixed order preserved in the manifest
    assert [f.facet for f in pack.pack_integrity.facets] == A.ASSEMBLY_ORDER


def test_domain_state_composer_reads_through_get_domain_state_g10():
    src = inspect.getsource(ds_mod)
    assert "get_domain_state" in src
    # G10: never a raw store / compute bypass in the facet composer.
    assert "compute_domain" not in src
    assert "read_parquet" not in src


# ---------------------------------------------------------------------------
# Look-ahead honesty (Constitution 18)
# ---------------------------------------------------------------------------


def test_contribution_flags_latest_only_on_past_knowledge_time():
    pack = A.EvidencePackAssembler().assemble(_req(knowledge_time=_PAST), deps=_healthy_deps())
    rec = _records(pack)["contribution"]
    assert rec.reason and "is_latest_only_flagged" in rec.reason


def test_contribution_not_flagged_for_live_now_run():
    pack = A.EvidencePackAssembler().assemble(_req(knowledge_time=_NOW), deps=_healthy_deps())
    rec = _records(pack)["contribution"]
    assert not (rec.reason and "is_latest_only_flagged" in rec.reason)


# ---------------------------------------------------------------------------
# ENRICHMENT contradiction failure => omit + reason, never raise
# ---------------------------------------------------------------------------


def test_contradiction_engine_failure_omits_facet_without_raising():
    deps = _healthy_deps(contradiction_engine=_RaisingContradictionEngine())
    pack = A.EvidencePackAssembler().assemble(_req(), deps=deps)  # must NOT raise
    assert pack.contradictions == ()
    assert pack.pack_integrity.pack_outcome != "degraded"
    assert _records(pack)["contradiction"].reason  # honest-empty: carries WHY
