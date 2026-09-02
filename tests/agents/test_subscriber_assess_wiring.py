"""Phase 172 Plan 04 Task 3 — SC-1 end-to-end assemble->assess wiring test.

Drives a synthetic ``MACRO_RELEASE`` through ``DomainAnalystSubscriber.handle`` with a
real :class:`~core.evidence.assembler.EvidencePackAssembler` + the non-empty
``stub_facet_deps`` (172-01) + a capturing ``assessment_sink`` and proves the SC-1
observable signal: the emitted ``DomainAssessment`` has real, populated ``claims[]``,
``integrity_state`` set, ``manifest.state_version == pack.identity.state_version``, and
the event's immutable ``knowledge_time`` (no wall-clock re-stamp) — ALONGSIDE the
unchanged legacy ``analyst.invoke`` (both producers emit, D-01).

A degraded case (all-``None`` ``FacetDeps``) proves the honest-empty vs real-claims
distinction (RESEARCH Pitfall 1): an unwired pack degrades to ``state_version =
"unavailable"`` and ``assess()`` abstains — so the "real claims" signal in the wired
case is not a false-positive.

Hermetic: no live VM102 — the stub ``domain_state_reader`` supplies the envelope. The
analyst is a real ``GrowthDomainAnalyst`` (real ``assess`` -> real templated claims)
with ``invoke`` wrapped to a spy so the legacy path fires independently WITHOUT needing
a heavy ``extra="forbid"`` ``Domain`` (the fixture passes a lightweight stand-in).
"""
from __future__ import annotations

from agents.domain_analyst_subscriber.subscriber import DomainAnalystSubscriber
from agents.growth_domain_analyst.agent import GrowthDomainAnalyst
from core.evidence.assembler import AssemblyRequest, EvidencePackAssembler, FacetDeps
from fingpt_core.contracts.evidence_pack import FacetIntegrity

from tests.agents.conftest import MACRO_RELEASE_KNOWLEDGE_TIME, MACRO_RELEASE_SLUG


class _SpyAnalyst(GrowthDomainAnalyst):
    """Real ``GrowthDomainAnalyst`` (real ``assess``) with ``invoke`` spied.

    D-01 keeps the legacy ``analyst.invoke`` UNCHANGED and independent of the
    governance path. The Wave-0 fixture feeds a lightweight ``_DomainStandin`` (not a
    heavy ``Domain``) into ``invoke``, so we override ``invoke`` to record the call
    rather than run the real narrative composer (which would need real ``Domain``
    fields). ``assess`` is inherited unchanged — it is pack-sourced, so the two
    producers are genuinely decoupled.
    """

    def __init__(self) -> None:
        super().__init__()
        self.invoke_calls: list = []

    def invoke(self, domain, context=None):  # type: ignore[override]
        self.invoke_calls.append((domain, context))
        return None


def test_macro_release_wires_assemble_assess(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-1: a live MACRO_RELEASE yields a real DomainAssessment via assemble->assess,
    alongside the unchanged legacy invoke (both producers emit)."""
    spy = _SpyAnalyst()
    captured: list = []
    assembler = EvidencePackAssembler()

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=assembler,
        facet_deps=stub_facet_deps,
        assessment_sink=captured.append,
    )

    subscriber.handle(macro_release_event)

    # --- D-01: BOTH producers emit ------------------------------------------------
    assert spy.invoke_calls, "legacy analyst.invoke did not fire (D-01 both-producers)"
    assert len(captured) == 1, "governance path emitted exactly one DomainAssessment"
    assessment = captured[0]

    # --- SC-1: real, non-empty claims (each claim_id populated) --------------------
    assert assessment.claims, "assessment has no claims — pack degraded/abstained?"
    assert all(c.claim_id for c in assessment.claims), "a claim_id is empty"

    # --- SC-1: integrity set + NOT abstaining (a real, non-'unavailable' pack) -----
    assert assessment.integrity_state is not None
    assert assessment.integrity_state != FacetIntegrity.UNAVAILABLE
    assert assessment.abstention_outcome is None, "real pack must not abstain"

    # --- SC-1: manifest reproducibility parity with the pack identity (D-10) -------
    # Build a reference pack with the SAME inputs; its identity.state_version must
    # equal the emitted assessment's manifest.state_version.
    ref_pack = assembler.assemble(
        AssemblyRequest(
            country=macro_release_event.country,
            domain_slug=MACRO_RELEASE_SLUG,
            knowledge_time=macro_release_event.knowledge_time,
        ),
        deps=stub_facet_deps,
    )
    assert ref_pack.identity.state_version != "unavailable", (
        "stub_facet_deps must yield a real state_version (else the test is vacuous)"
    )
    assert assessment.manifest.state_version == ref_pack.identity.state_version
    assert assessment.state_version == ref_pack.identity.state_version

    # --- SC-1: knowledge_time is the event's immutable as-of (no wall-clock re-stamp)
    assert assessment.knowledge_time == macro_release_event.knowledge_time
    assert assessment.knowledge_time == MACRO_RELEASE_KNOWLEDGE_TIME
    assert assessment.knowledge_time.tzinfo is not None


def test_no_facet_deps_abstains(macro_release_event, stub_domain_fetcher):
    """RESEARCH Pitfall 1: an all-None FacetDeps -> honest-empty pack -> assess()
    abstains. Proves the real-claims signal above is not a false-positive."""
    spy = _SpyAnalyst()
    captured: list = []

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=EvidencePackAssembler(),
        facet_deps=FacetDeps(),  # unwired -> every facet UNAVAILABLE (honest-empty)
        assessment_sink=captured.append,
    )

    subscriber.handle(macro_release_event)

    # Legacy path still fires (D-01 is independent of the governance path).
    assert spy.invoke_calls, "legacy analyst.invoke did not fire in the degraded case"
    assert len(captured) == 1
    assessment = captured[0]

    # Honest-empty: the unwired pack degrades to the 'unavailable' sentinel and the
    # deterministic assess() abstains rather than fabricating a real state.
    assert assessment.state_version == "unavailable"
    assert assessment.integrity_state == FacetIntegrity.UNAVAILABLE
    assert assessment.abstention_outcome is not None, (
        "an unavailable pack must produce an abstention outcome"
    )
