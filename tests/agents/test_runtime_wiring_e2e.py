"""Phase 172 Plan 06 Task 1 — SC-6 full-chain runtime-wiring E2E.

This is the phase-closing automated proof: ONE synthetic ``MACRO_RELEASE`` driven
through :meth:`DomainAnalystSubscriber.handle` exercises the WHOLE v6.5 governance
pipeline end-to-end in a single run —

    fetch (stub) -> assemble() -> AssessmentCache single-flight -> assess()
                 -> run_panel() -> emit

— and the emitted ``DomainAssessment`` is asserted to carry per-claim provenance
(populated ``claim_id`` + a reproducibility ``manifest`` whose ``state_version`` has
parity with the pack identity), the immutable ``knowledge_time`` (no wall-clock
re-stamp — Phase 168 D-06a), AND a ``run_panel`` :class:`CriticVerdict`
(ACCEPT/REFINE/REJECT). Both producers fire (the legacy ``analyst.invoke`` and the new
governance path — D-01 ALONGSIDE).

Where 172-04 (SC-1) proved assemble->assess, 172-05 (SC-2/SC-4) proved the panel splice
and the cache seam, this test proves ALL FOUR stages fire together in one release AND
pins them to the static orphan-guard: SC-6 has two halves — a live full-chain run and
a static "no stage is orphaned" scan — so this module asserts BOTH, closing the phase.

Hermetic: no live VM102 (the 172-01 ``stub_facet_deps`` supplies the domain_state
envelope), no Mongo/Redis (an in-memory ``AssessmentCache`` backend + a recording fake
Redis). The analyst is a real ``GrowthDomainAnalyst`` (real, deterministic ``assess`` ->
real templated claims + real lens inputs) with ``invoke`` spied and ``assess`` COUNTED so
the full chain runs against a genuine assessment rather than a mock.
"""
from __future__ import annotations

import importlib

from agents.domain_analyst_subscriber.subscriber import (
    _ASSESS_DETAIL_LEVEL,
    _ASSESS_HORIZON,
    _ASSESS_NARRATIVE_MODE,
    _ASSESS_TASK,
    DomainAnalystSubscriber,
)
from agents.growth_domain_analyst.agent import GrowthDomainAnalyst
from core.contracts.schemas import CriticVerdict
from core.evidence.assembler import AssemblyRequest, EvidencePackAssembler
from core.persistence.assessment_cache import AssessmentCache, compute_work_key
from fingpt_core.contracts.evidence_pack import FacetIntegrity

from tests.agents.conftest import MACRO_RELEASE_KNOWLEDGE_TIME, MACRO_RELEASE_SLUG


class _FullChainAnalyst(GrowthDomainAnalyst):
    """Real ``GrowthDomainAnalyst`` with ``invoke`` spied + ``assess`` COUNTED.

    ``assess`` delegates to the real deterministic base (so the emitted record is a
    genuine ``DomainAssessment`` the panel can adjudicate); the counter proves the
    expensive stage ran exactly once through the cache seam. ``invoke`` is recorded
    (D-01 both-producers) without needing a heavy ``extra='forbid'`` ``Domain``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.invoke_calls: list = []
        self.assess_calls: int = 0

    def invoke(self, domain, context=None):  # type: ignore[override]
        self.invoke_calls.append((domain, context))
        return None

    def assess(self, pack, *, knowledge_time=None):  # type: ignore[override]
        self.assess_calls += 1
        return super().assess(pack, knowledge_time=knowledge_time)


class _FakeBackend:
    """In-memory Mongo-shaped get/put backend (the AssessmentCache's narrow surface)."""

    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, doc_id):
        return self.store.get(doc_id)

    def put(self, doc_id, document):
        self.store[doc_id] = document


class _RecordingRedis:
    """Fake Redis recording every ``SET NX EX`` key (the single-flight work_key)."""

    def __init__(self) -> None:
        self.keys: list = []

    def set(self, key, value, nx=False, ex=None):
        self.keys.append(key)
        return True  # first-in acquires


def test_macro_release_drives_full_chain_end_to_end(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-6: a single synthetic MACRO_RELEASE drives
    fetch -> assemble -> (cache single-flight) -> assess -> run_panel -> emit through
    subscriber.handle, and the emitted DomainAssessment carries per-claim provenance
    (claim_id + manifest.state_version parity) + the immutable knowledge_time + a panel
    CriticVerdict — with BOTH producers (legacy invoke + governance path) firing."""
    spy = _FullChainAnalyst()
    captured: list = []
    assembler = EvidencePackAssembler()
    cache = AssessmentCache(_FakeBackend())
    redis = _RecordingRedis()

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=assembler,
        facet_deps=stub_facet_deps,
        assessment_cache=cache,
        redis_client=redis,
        # Two-arg sink: the full chain emits (assessment, verdict) together (SC-2).
        assessment_sink=lambda assessment, verdict: captured.append(
            (assessment, verdict)
        ),
    )

    # --- ONE release drives the WHOLE chain -----------------------------------------
    subscriber.handle(macro_release_event)

    # === Stage: fetch + legacy producer (D-01 ALONGSIDE) ============================
    assert spy.invoke_calls, "legacy analyst.invoke did not fire (D-01 both-producers)"

    # === Stage: assemble -> cache single-flight -> assess (governance producer) =====
    assert spy.assess_calls == 1, (
        f"assess() must run exactly once for the single release, got {spy.assess_calls}"
    )
    assert len(captured) == 1, "governance path emitted exactly one adjudicated result"
    assessment, verdict = captured[0]

    # The single-flight lock was acquired once (the miss) on the D-04 work_key — proof
    # the cache seam actually ran between assemble() and assess().
    ref_pack = assembler.assemble(
        AssemblyRequest(
            country=macro_release_event.country,
            domain_slug=MACRO_RELEASE_SLUG,
            knowledge_time=macro_release_event.knowledge_time,
        ),
        deps=stub_facet_deps,
    )
    expected_work_key = compute_work_key(
        agent_type=getattr(spy, "AGENT_ID", "") or type(spy).__name__,
        domain=MACRO_RELEASE_SLUG,
        geography=ref_pack.identity.country,
        sector=None,
        state_version=ref_pack.identity.state_version,
        knowledge_time=MACRO_RELEASE_KNOWLEDGE_TIME,
        detail_level=_ASSESS_DETAIL_LEVEL,
        horizon=_ASSESS_HORIZON,
        narrative_mode=_ASSESS_NARRATIVE_MODE,
        task=_ASSESS_TASK,
    )
    assert redis.keys == [expected_work_key], (
        "single-flight lock must be acquired exactly once (the miss) on the D-04 "
        "work_key — proves the cache seam fired between assemble() and assess()"
    )

    # === Per-claim provenance: real, non-empty claims (each claim_id populated) ======
    assert assessment.claims, "assessment has no claims — pack degraded/abstained?"
    assert all(c.claim_id for c in assessment.claims), "a claim_id is empty"

    # === Per-claim provenance: reproducibility manifest with state_version parity =====
    assert ref_pack.identity.state_version != "unavailable", (
        "stub_facet_deps must yield a real state_version (else the test is vacuous)"
    )
    assert assessment.manifest is not None, "assessment has no reproducibility manifest"
    assert assessment.manifest.state_version == ref_pack.identity.state_version, (
        "manifest.state_version must match the pack identity (D-10 reproducibility)"
    )
    assert assessment.state_version == ref_pack.identity.state_version

    # === Real (non-'unavailable') pack: integrity set, not abstaining ================
    assert assessment.integrity_state is not None
    assert assessment.integrity_state != FacetIntegrity.UNAVAILABLE
    assert assessment.abstention_outcome is None, "real pack must not abstain"

    # === Immutable knowledge_time (no wall-clock re-stamp — 168 D-06a) ===============
    assert assessment.knowledge_time == macro_release_event.knowledge_time
    assert assessment.knowledge_time == MACRO_RELEASE_KNOWLEDGE_TIME
    assert assessment.knowledge_time.tzinfo is not None

    # === Stage: run_panel adjudicated the emit (SC-2 CriticVerdict attached) =========
    assert isinstance(verdict, CriticVerdict), "emit did not carry a panel CriticVerdict"
    assert verdict.verdict in {"ACCEPT", "REFINE", "REJECT"}
    # The wired pack does NOT abstain, so the five lenses actually ran — this is NOT the
    # domain-native 0-lens short-circuit path.
    assert not (verdict.source_critic_verdict_id or "").startswith(
        "scv-panel-abstain-"
    ), "wired (non-abstaining) pack must NOT take the 0-lens short-circuit path"


def test_orphan_guard_is_green_all_stages_have_live_callers():
    """SC-6 (the static half): assemble()/assess()/run_panel() each have >=1 non-test
    caller — the orphan-runtime regression is CLOSED. The full-chain test above proves
    the stages FIRE; this proves none is reachable ONLY from tests. Both halves must
    hold for SC-6, so the phase gate asserts them together (import + drive the guard)."""
    guard = importlib.import_module(
        "tests.agents.test_runtime_wiring_orphan_guard"
    )

    # Drive the guard's parametrised body directly for each of the three needles; any
    # orphaned stage raises AssertionError with the SC-6 ORPHAN diagnostic.
    for spec in guard._NEEDLES:
        guard.test_callable_has_non_test_caller(spec)

    # And assert we actually checked the three v6.5 stages (not a silently-empty set).
    checked = {spec.callable_name for spec in guard._NEEDLES}
    assert checked == {"assemble", "assess", "run_panel"}, (
        f"orphan-guard must cover all three v6.5 stages, covered {checked}"
    )
