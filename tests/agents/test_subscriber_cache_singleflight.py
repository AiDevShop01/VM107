"""Phase 172 Plan 05 Task 3 — SC-4 (D-04) AssessmentCache single-flight test.

Proves the SC-4 observable signal: a repeat identical release (same
``pack.identity.state_version``) reuses the cached ``DomainAssessment`` — ``assess()``
is NOT re-executed (spy count == 1) — because the ``AssessmentCache`` is consulted
AFTER ``assemble()`` (cheap) but BEFORE ``assess()``/``run_panel()`` (expensive),
keyed on the D-04 identity ``work_key = (domain_slug, pack.identity.state_version)``
with the immutable ``knowledge_time``.

Also proves degrade-safety: with ``redis_client=None`` the single-flight lock is a
no-op (``acquire_single_flight`` returns True — proceed without lock) yet the cache
still dedups the assess per distinct release.

Hermetic: an in-memory Mongo-shaped backend for the ``AssessmentCache`` + a recording
fake Redis; no live Mongo/Redis/VM102. The analyst is a real ``GrowthDomainAnalyst``
with ``invoke`` spied and ``assess`` COUNTED (delegating to the real deterministic
assess so the cached record is a genuine ``DomainAssessment``).
"""
from __future__ import annotations

from agents.domain_analyst_subscriber.subscriber import (
    _ASSESS_DETAIL_LEVEL,
    _ASSESS_HORIZON,
    _ASSESS_NARRATIVE_MODE,
    _ASSESS_TASK,
    DomainAnalystSubscriber,
)
from agents.growth_domain_analyst.agent import GrowthDomainAnalyst
from core.evidence.assembler import AssemblyRequest, EvidencePackAssembler
from core.persistence.assessment_cache import AssessmentCache, compute_work_key

from tests.agents.conftest import MACRO_RELEASE_KNOWLEDGE_TIME, MACRO_RELEASE_SLUG


class _AssessSpyAnalyst(GrowthDomainAnalyst):
    """Real ``GrowthDomainAnalyst`` with ``invoke`` spied + ``assess`` COUNTED.

    ``assess`` delegates to the real deterministic base so the cached record round-trips
    as a genuine ``DomainAssessment`` — the counter is the SC-4 proof that a cache HIT
    skips the expensive compute.
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


def _second_release(event):
    """A DISTINCT release (new event_id) for the SAME domain/state — so idempotency
    does not short-circuit but the cache does (the whole point of SC-4)."""
    return event.model_copy(update={"event_id": "evt-172-macro-growth-0002"})


def test_repeat_release_reuses_cache_assess_runs_once(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-4: two distinct releases with the same state_version -> the second reuses the
    cached DomainAssessment; assess() spy count == 1; the single-flight work_key keys on
    (domain_slug, pack.identity.state_version)."""
    spy = _AssessSpyAnalyst()
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
        assessment_sink=lambda assessment, verdict: captured.append(assessment),
        debounce_seconds=0,  # same slug twice -> disable the debounce window
    )

    event1 = macro_release_event
    event2 = _second_release(macro_release_event)

    subscriber.handle(event1)  # MISS -> assess + populate
    subscriber.handle(event2)  # HIT  -> reuse cached assessment (no assess)

    # SC-4 core signal: the expensive assess ran EXACTLY once across two releases.
    assert spy.assess_calls == 1, (
        f"expected a single assess() across two identical releases, "
        f"got {spy.assess_calls} (cache single-flight not honored?)"
    )

    # Both releases still emitted (the second emits the REUSED assessment).
    assert len(captured) == 2, "both releases must emit (second reuses the cache)"
    assert captured[0].state_version == captured[1].state_version
    assert captured[0].state_version != "unavailable", (
        "stub_facet_deps must yield a real state_version (else the test is vacuous)"
    )

    # SC-4 identity: the single-flight key the subscriber acquired reflects D-04 —
    # (domain_slug, pack.identity.state_version) + immutable knowledge_time — and was
    # acquired ONCE (the miss), not on the hit.
    ref_pack = assembler.assemble(
        AssemblyRequest(
            country=macro_release_event.country,
            domain_slug=MACRO_RELEASE_SLUG,
            knowledge_time=macro_release_event.knowledge_time,
        ),
        deps=stub_facet_deps,
    )
    state_version = ref_pack.identity.state_version
    expected_work_key = compute_work_key(
        agent_type=getattr(spy, "AGENT_ID", "") or type(spy).__name__,
        domain=MACRO_RELEASE_SLUG,
        geography=ref_pack.identity.country,
        sector=None,
        state_version=state_version,
        knowledge_time=MACRO_RELEASE_KNOWLEDGE_TIME,
        detail_level=_ASSESS_DETAIL_LEVEL,
        horizon=_ASSESS_HORIZON,
        narrative_mode=_ASSESS_NARRATIVE_MODE,
        task=_ASSESS_TASK,
    )
    assert redis.keys == [expected_work_key], (
        "single-flight lock must be acquired exactly once (the miss) on the D-04 "
        "work_key derived from (domain_slug, state_version)"
    )
    assert expected_work_key.startswith("wk_")

    # A DIFFERENT state_version -> a DIFFERENT work_key (proves it keys on state_version,
    # not just the slug — the D-04 tuple shape).
    other_key = compute_work_key(
        agent_type=getattr(spy, "AGENT_ID", "") or type(spy).__name__,
        domain=MACRO_RELEASE_SLUG,
        geography=ref_pack.identity.country,
        sector=None,
        state_version=state_version + ":BUMPED",
        knowledge_time=MACRO_RELEASE_KNOWLEDGE_TIME,
        detail_level=_ASSESS_DETAIL_LEVEL,
        horizon=_ASSESS_HORIZON,
        narrative_mode=_ASSESS_NARRATIVE_MODE,
        task=_ASSESS_TASK,
    )
    assert other_key != expected_work_key


def test_redis_down_degrades_safely(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-4 degrade-safety: redis_client=None -> acquire_single_flight is a no-op
    (proceed without lock) yet the cache still dedups — one assess per distinct release
    (state_version-identical), both emit correctly."""
    spy = _AssessSpyAnalyst()
    captured: list = []
    cache = AssessmentCache(_FakeBackend())

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=EvidencePackAssembler(),
        facet_deps=stub_facet_deps,
        assessment_cache=cache,
        redis_client=None,  # Redis down / unwired -> proceed WITHOUT lock
        assessment_sink=lambda assessment, verdict: captured.append(assessment),
        debounce_seconds=0,
    )

    subscriber.handle(macro_release_event)
    subscriber.handle(_second_release(macro_release_event))

    # Still correct: the cache dedups the identical-state release even with no lock.
    assert spy.assess_calls == 1, "no-lock path must still dedup via the cache"
    assert len(captured) == 2
    assert captured[0].state_version == captured[1].state_version
    assert captured[0].state_version != "unavailable"


def test_no_cache_wired_runs_assess_each_time(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-4 optional-DI: with assessment_cache=None the seam is skipped entirely and
    the path proceeds uncached (assess runs per distinct release) — still correct."""
    spy = _AssessSpyAnalyst()
    captured: list = []

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=EvidencePackAssembler(),
        facet_deps=stub_facet_deps,
        # assessment_cache omitted -> proceed without cache/lock.
        assessment_sink=lambda assessment, verdict: captured.append(assessment),
        debounce_seconds=0,
    )

    subscriber.handle(macro_release_event)
    subscriber.handle(_second_release(macro_release_event))

    assert spy.assess_calls == 2, "uncached path must run assess per distinct release"
    assert len(captured) == 2
