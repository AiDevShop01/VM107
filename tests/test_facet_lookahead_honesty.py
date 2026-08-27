"""Phase 168 Plan 08 — look-ahead honesty regression across the facet composers.

Closes GAP 2 + GAP 3 (168-VERIFICATION.md): the REQUIRED domain_state spine and
the two ENRICHMENT facets (historical_context / evidence_ranking) must be honest
about a materially-past ``knowledge_time`` — a point-in-time replay must NOT get a
silent "latest" read with zero trace in the pack (Constitution 18).

  * Test D: domain_state with meta.as_of_honored=False (a past as-of) records a
    look-ahead reason on the outcome (contribution.py's is_latest_only_flagged shape).
  * Test E: meta.as_of_honored=True (live) records NO look-ahead reason.
  * Test G/H/I (Task 2): the two ENRICHMENT facets forward to_iso(req.knowledge_time)
    to their reader seams and flag a materially-past as-of.

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). All VM102
seams are injected fakes capturing the knowledge_time kwarg they receive.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fingpt_core.contracts.evidence_pack import (
    HistoricalPercentileFacet,
    PriorAssessmentFacet,
)

from core.evidence import assembler as A
from core.evidence.facets import to_iso
from core.evidence.facets.domain_state import compose_domain_state
from core.evidence.facets.evidence_ranking import compose_evidence_ranking
from core.evidence.facets.historical_context import compose_historical_context

_PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)
_LIVE = datetime.now(timezone.utc)

_LOOKAHEAD = "is_latest_only_flagged"

_CURRENT = {"label": "Stable", "score": 0.1, "confidence": 0.5, "state_version": "US:mp:v1"}


def _req(knowledge_time) -> A.AssemblyRequest:
    return A.AssemblyRequest(country="US", domain_slug="inflation", knowledge_time=knowledge_time)


# ---------------------------------------------------------------------------
# domain_state look-ahead honesty (GAP 2)
# ---------------------------------------------------------------------------


class _FakeDomainStateReader:
    def __init__(self, envelope):
        self._env = envelope

    def get_domain_state(self, country, domain_slug, *, knowledge_time=None, previous=False):
        return self._env


def _ds_env(*, as_of_honored, latest_only=True):
    return {
        "status": "ok",
        "data": {"current": _CURRENT, "previous": None},
        "meta": {
            "state_version": "US:mp:v1",
            "latest_only": latest_only,
            "as_of_honored": as_of_honored,
            "reason": None,
        },
    }


def _ds_ctx(envelope, knowledge_time) -> A.AssemblyContext:
    return A.AssemblyContext(
        request=_req(knowledge_time),
        deps=A.FacetDeps(domain_state_reader=_FakeDomainStateReader(envelope)),
    )


def test_D_past_as_of_records_lookahead_on_domain_state():
    out = compose_domain_state(_ds_ctx(_ds_env(as_of_honored=False), _PAST))
    assert out.ok is True
    assert out.reason and _LOOKAHEAD in out.reason


def test_E_live_read_records_no_lookahead_on_domain_state():
    out = compose_domain_state(_ds_ctx(_ds_env(as_of_honored=True), _LIVE))
    assert out.ok is True
    assert not (out.reason and _LOOKAHEAD in out.reason)


# ---------------------------------------------------------------------------
# ENRICHMENT facets forward req.knowledge_time (GAP 3) — Task 2
# ---------------------------------------------------------------------------

_PCT = {"percentile": 72.5, "window": "10y", "indicator": "CPIAUCSL", "surprise": -0.3}


class _CapturingPercentileReader:
    def __init__(self, result):
        self._result = result
        self.knowledge_time = "__unset__"

    def historical_percentile(self, country, domain_slug, *, knowledge_time=None):
        self.knowledge_time = knowledge_time
        return self._result


_HITS = [
    {"assessment_id": "a-top", "outcome": "cut-signalled", "knowledge_time": "2026-07-01T00:00:00+00:00", "score": 0.93},
    {"assessment_id": "a-low", "outcome": "neutral", "knowledge_time": "2026-05-01T00:00:00+00:00", "score": 0.55},
]


class _CapturingEvidenceReader:
    def __init__(self, hits):
        self._hits = hits
        self.knowledge_time = "__unset__"

    def search(self, country, domain_slug, *, knowledge_time=None, limit=5):
        self.knowledge_time = knowledge_time
        return self._hits


def test_G_historical_context_forwards_knowledge_time_and_flags_past(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    reader = _CapturingPercentileReader(_PCT)
    ctx = A.AssemblyContext(request=_req(_PAST), deps=A.FacetDeps(percentile_reader=reader))
    out = compose_historical_context(ctx)
    assert out.ok is True
    assert isinstance(out.value, HistoricalPercentileFacet)
    assert reader.knowledge_time == to_iso(_PAST)  # forwarded, NOT None
    assert out.reason and _LOOKAHEAD in out.reason


def test_H_evidence_ranking_forwards_knowledge_time_and_flags_past():
    reader = _CapturingEvidenceReader(_HITS)
    ctx = A.AssemblyContext(request=_req(_PAST), deps=A.FacetDeps(evidence_reader=reader))
    out = compose_evidence_ranking(ctx)
    assert out.ok is True
    assert isinstance(out.value, PriorAssessmentFacet)
    assert reader.knowledge_time == to_iso(_PAST)  # forwarded, NOT None
    assert out.reason and _LOOKAHEAD in out.reason


def test_I_live_run_records_no_lookahead_and_both_facets_serve(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    hc_reader = _CapturingPercentileReader(_PCT)
    hc_ctx = A.AssemblyContext(request=_req(_LIVE), deps=A.FacetDeps(percentile_reader=hc_reader))
    hc_out = compose_historical_context(hc_ctx)
    assert hc_out.ok is True
    assert hc_reader.knowledge_time == to_iso(_LIVE)
    assert not (hc_out.reason and _LOOKAHEAD in hc_out.reason)

    ev_reader = _CapturingEvidenceReader(_HITS)
    ev_ctx = A.AssemblyContext(request=_req(_LIVE), deps=A.FacetDeps(evidence_reader=ev_reader))
    ev_out = compose_evidence_ranking(ev_ctx)
    assert ev_out.ok is True
    assert ev_reader.knowledge_time == to_iso(_LIVE)
    assert not (ev_out.reason and _LOOKAHEAD in ev_out.reason)
