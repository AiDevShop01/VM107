"""Phase 168 Plan 06 Task 2 — Evidence retrieval-ranking facet (Qdrant, hits-first).

Proves the ENRICHMENT Evidence-ranking facet (D-01/D-02 + AGV-07 hits-first). It
retrieves + ranks relevant prior assessments over Qdrant and populates the
``prior_assessment`` facet slot, degrading gracefully:

  * HITS-FIRST (AGV-07 / project memory feedback_health_bus_reads_must_be_hits_first):
    real hits are returned EVEN WHEN the SourceHealthRegistry reports the Qdrant
    source DEGRADED — the degraded read is gated behind ``if not hits``, so real
    results are never discarded as degraded,
  * no hits / Qdrant down => the facet is OMITTED with a reason (ENRICHMENT), the
    pack is never bricked,
  * deterministic ranking (score desc, id asc as a stable tiebreak).

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). Qdrant +
SourceHealthRegistry are injected fakes — no live services.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from fingpt_core.contracts.evidence_pack import (
    DomainEvidencePack,
    DomainStateFacet,
    FacetIntegrity,
    PriorAssessmentFacet,
    StateDiffFacet,
)

from core.evidence import assembler as A
from core.evidence import tiers as T
from core.evidence.facets import evidence_ranking as ev_mod

_NOW = datetime.now(timezone.utc)


def _healthy_required_composers() -> dict:
    """Wire the 2 REQUIRED reuse facets healthy so the ENRICHMENT Evidence facet
    is isolated (unwired REQUIRED facets would dominate the pack as ``degraded``)."""

    def _ds(ctx):
        return T.FacetOutcome(
            name="domain_state",
            ok=True,
            integrity=FacetIntegrity.NEUTRAL,
            value=DomainStateFacet(state_version="US:inf:v1", label="Cooling", score=0.1),
        )

    def _sd(ctx):
        return T.FacetOutcome(
            name="state_diff",
            ok=True,
            integrity=FacetIntegrity.NEUTRAL,
            value=StateDiffFacet(changed=False, current_label="Cooling"),
        )

    return {"domain_state": _ds, "state_diff": _sd}

_HITS = [
    {"assessment_id": "a-mid", "outcome": "hawkish-hold", "knowledge_time": "2026-06-01T00:00:00+00:00", "score": 0.71},
    {"assessment_id": "a-top", "outcome": "cut-signalled", "knowledge_time": "2026-07-01T00:00:00+00:00", "score": 0.93},
    {"assessment_id": "a-low", "outcome": "neutral", "knowledge_time": "2026-05-01T00:00:00+00:00", "score": 0.55},
]


class _FakeEvidenceReader:
    def __init__(self, hits):
        self._hits = hits

    def search(self, country, domain_slug, *, knowledge_time=None, limit=5):
        return self._hits


class _FakeSourceHealth:
    """Mimics SourceHealthRegistry.snapshot() -> {source_id: obj(available: bool)}."""

    def __init__(self, available: bool):
        self._available = available

    def snapshot(self):
        class _H:
            available = self._available
        return {ev_mod.EVIDENCE_SOURCE_ID: _H()}


def _req(knowledge_time=_NOW) -> A.AssemblyRequest:
    return A.AssemblyRequest(country="US", domain_slug="inflation", knowledge_time=knowledge_time)


def _ctx(reader, source_health=None) -> A.AssemblyContext:
    return A.AssemblyContext(
        request=_req(), deps=A.FacetDeps(evidence_reader=reader, source_health=source_health)
    )


def _records(pack: DomainEvidencePack) -> dict:
    return {f.facet: f for f in pack.pack_integrity.facets}


# ---------------------------------------------------------------------------
# HITS-FIRST — real hits survive a DEGRADED health-bus signal
# ---------------------------------------------------------------------------


def test_real_hits_survive_a_degraded_source_health_bus():
    # The bus reports Qdrant DEGRADED, but real hits came back => hits win.
    out = ev_mod.compose_evidence_ranking(_ctx(_FakeEvidenceReader(_HITS), _FakeSourceHealth(available=False)))
    assert out.ok is True
    assert isinstance(out.value, PriorAssessmentFacet)
    # deterministic: highest-score hit is selected
    assert out.value.assessment_id == "a-top"
    assert out.value.outcome == "cut-signalled"


def test_hits_first_gate_is_in_the_source():
    src = inspect.getsource(ev_mod)
    assert "if not hits" in src  # the degraded read is gated behind no-hits


# ---------------------------------------------------------------------------
# No hits => consult the bus, omit with a reason (ENRICHMENT), never brick
# ---------------------------------------------------------------------------


def test_no_hits_qdrant_degraded_omits_with_reason():
    out = ev_mod.compose_evidence_ranking(_ctx(_FakeEvidenceReader([]), _FakeSourceHealth(available=False)))
    assert out.ok is False
    assert out.reason and ("degrad" in out.reason.lower() or "down" in out.reason.lower())


def test_no_hits_healthy_bus_omits_neutral_reason():
    out = ev_mod.compose_evidence_ranking(_ctx(_FakeEvidenceReader([]), _FakeSourceHealth(available=True)))
    assert out.ok is False
    assert out.reason and "no" in out.reason.lower()


def test_no_evidence_reader_omits_with_reason():
    out = ev_mod.compose_evidence_ranking(A.AssemblyContext(request=_req(), deps=A.FacetDeps()))
    assert out.ok is False
    assert out.reason


# ---------------------------------------------------------------------------
# Wired into the assembler => populates prior_assessment, never bricks
# ---------------------------------------------------------------------------


def test_registered_populates_prior_assessment():
    deps = A.FacetDeps(evidence_reader=_FakeEvidenceReader(_HITS))
    assembler = A.EvidencePackAssembler(composers=_healthy_required_composers())
    pack = assembler.assemble(_req(), deps=deps)  # must NOT raise
    assert isinstance(pack.prior_assessment, PriorAssessmentFacet)
    assert pack.prior_assessment.assessment_id == "a-top"
    assert pack.pack_integrity.pack_outcome != "degraded"
