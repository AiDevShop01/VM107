"""Phase 168 Plan 08 Task 1 — domain_state / state_diff classification regression.

Closes the coverage gap that let GAP 1 (168-VERIFICATION.md) ship green: the
phase suite only ever fixtured VM102 ``status="ok"``. VM102 emits
``status="degraded"`` (confidence < 0.6) with a fully-valid ``data.current`` — a
legitimate LOWER-CONFIDENCE result, not an outage. The REQUIRED domain_state
composer must flow that read THROUGH as a successful, STALE-tagged
``DomainStateFacet`` — never discard it as UNAVAILABLE.

  * Test A: status="degraded" + populated current => ok=True, integrity STALE,
    value carries the real current label/score (data NOT discarded).
  * Test B: status="unavailable" (and status="ok" with a missing current)
    => ok=False, integrity UNAVAILABLE.
  * Test C: status="ok" + current => ok=True, integrity NEUTRAL (happy path
    preserved, no regression).
  * Test F: a degraded/look-ahead spine propagates STALE + the look-ahead reason
    onto the StateDiffFacet (state_diff is not silently NEUTRAL).

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). VM102 is
an injected fake at the typed ``domain_state_reader`` seam — no live service.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fingpt_core.contracts.evidence_pack import (
    DomainStateFacet,
    FacetIntegrity,
    StateDiffFacet,
)

from core.evidence import assembler as A
from core.evidence.facets.domain_state import compose_domain_state
from core.evidence.facets.state_diff import compose_state_diff

_PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)
_LIVE = datetime.now(timezone.utc)

_CURRENT = {"label": "Stable", "score": 0.1, "confidence": 0.5, "state_version": "US:mp:v1"}
_PREVIOUS = {"label": "Easing", "score": -0.2, "confidence": 0.8, "state_version": "US:mp:v0"}


class _FakeDomainStateReader:
    def __init__(self, envelope):
        self._env = envelope
        self.calls: list[dict] = []

    def get_domain_state(self, country, domain_slug, *, knowledge_time=None, previous=False):
        self.calls.append(
            {"country": country, "domain_slug": domain_slug, "knowledge_time": knowledge_time, "previous": previous}
        )
        return self._env


def _env(*, status="ok", current=None, previous=None, as_of_honored=True, latest_only=True, reason=None):
    return {
        "status": status,
        "data": {"current": current, "previous": previous},
        "meta": {
            "state_version": "US:mp:v1",
            "previous_state_version": "US:mp:v0",
            "knowledge_time": None,
            "latest_only": latest_only,
            "as_of_honored": as_of_honored,
            "reason": reason,
        },
    }


def _ctx(envelope, knowledge_time=_LIVE) -> A.AssemblyContext:
    return A.AssemblyContext(
        request=A.AssemblyRequest(country="US", domain_slug="monetary_policy", knowledge_time=knowledge_time),
        deps=A.FacetDeps(domain_state_reader=_FakeDomainStateReader(envelope)),
    )


# ---------------------------------------------------------------------------
# Test A — GAP 1: a degraded read with real data flows through as STALE success
# ---------------------------------------------------------------------------


def test_degraded_with_current_flows_through_as_stale_success():
    out = compose_domain_state(_ctx(_env(status="degraded", current=_CURRENT)))
    assert out.ok is True
    assert out.integrity == FacetIntegrity.STALE
    assert isinstance(out.value, DomainStateFacet)
    assert out.value.label == "Stable"  # the real current label — NOT discarded
    assert out.value.score == 0.1
    assert out.value.integrity == FacetIntegrity.STALE


# ---------------------------------------------------------------------------
# Test B — GAP 1: unavailable / missing-current stays UNAVAILABLE
# ---------------------------------------------------------------------------


def test_unavailable_status_is_unavailable():
    out = compose_domain_state(_ctx(_env(status="unavailable", current=None, reason="provider down")))
    assert out.ok is False
    assert out.integrity == FacetIntegrity.UNAVAILABLE


def test_ok_status_missing_current_is_unavailable():
    out = compose_domain_state(_ctx(_env(status="ok", current=None)))
    assert out.ok is False
    assert out.integrity == FacetIntegrity.UNAVAILABLE


# ---------------------------------------------------------------------------
# Test C — GAP 1: the ok happy-path is preserved (NEUTRAL)
# ---------------------------------------------------------------------------


def test_ok_status_with_current_is_neutral_success():
    out = compose_domain_state(_ctx(_env(status="ok", current=_CURRENT)))
    assert out.ok is True
    assert out.integrity == FacetIntegrity.NEUTRAL
    assert isinstance(out.value, DomainStateFacet)
    assert out.value.label == "Stable"
    assert out.value.integrity == FacetIntegrity.NEUTRAL


# ---------------------------------------------------------------------------
# Test F — GAP 2 propagation: a degraded/look-ahead spine tags state_diff STALE
# ---------------------------------------------------------------------------


def test_state_diff_propagates_stale_and_lookahead_from_a_degraded_spine():
    ctx = _ctx(
        _env(status="degraded", current=_CURRENT, previous=_PREVIOUS, as_of_honored=False),
        knowledge_time=_PAST,
    )
    ds = compose_domain_state(ctx)
    ctx.outcomes["domain_state"] = ds
    assert ds.ok is True and ds.integrity == FacetIntegrity.STALE

    sd = compose_state_diff(ctx)
    assert sd.ok is True
    assert isinstance(sd.value, StateDiffFacet)
    assert sd.value.integrity == FacetIntegrity.STALE  # the diff is not silently NEUTRAL
    assert sd.reason and "is_latest_only_flagged" in sd.reason  # look-ahead propagated


def test_state_diff_healthy_spine_stays_neutral():
    ctx = _ctx(_env(status="ok", current=_CURRENT, previous=_PREVIOUS), knowledge_time=_LIVE)
    ctx.outcomes["domain_state"] = compose_domain_state(ctx)
    sd = compose_state_diff(ctx)
    assert sd.ok is True
    assert sd.value.integrity == FacetIntegrity.NEUTRAL
    assert not sd.reason  # no look-ahead on a live, healthy spine
