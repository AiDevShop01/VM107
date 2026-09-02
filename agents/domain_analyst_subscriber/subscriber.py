"""Phase 95-12 — domain_analyst_subscriber listener service.

Single process subscribing all 12 long-lived domain analysts (CONTEXT §F)
to the EventBus :class:`EventType.MACRO_RELEASE` stream, filtered per
agent by ``event.payload.affected_domains`` containing the analyst's
``DOMAIN_SLUG``.

Keeps container count flat (1 sibling service for 12 agents — see plan
95-12 §F). Ships as a docker-compose sibling service per
``feedback_mgmt_commands_need_compose_service``: the listener must
survive backend restarts and never be a mgmt-command-only worker.

Design notes
------------
* Registry-driven dispatch — the 12 analyst classes are imported
  dynamically via :func:`load_analysts`; no hardcoded ``if`` ladder
  (Phase 47.6 capability registry lock).
* 30s debounce per ``(slug, snapshot_version)`` — a bursty release
  window collapses to one analyst invocation.
* Idempotency key ``(event_id, snapshot_version)`` — repeated events
  short-circuit before any analyst invoke (Pitfall 6 — race conditions).
* One analyst raising an exception MUST NOT break the others — every
  invoke is wrapped in try/except (Phase 94 §B.3 isolation lock).
* Fail-fast on missing env vars (``REDIS_HOST`` / ``REDIS_PORT``) — no
  fallback defaults per ``feedback_env_driven_no_fallbacks``.

Phase 94 pillar analyst code is UNCHANGED (Open Q 4 Path A resolution +
Pitfall 9 mitigation) — the Chief Economist Synthesizer composes the 12
new Domain SpecialistResponses + 4 existing Pillar SpecialistResponses
naturally via citation count.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from contracts.economic_intelligence.events import EconomicEvent, EventType
from core.agents.specialized_critic.panel import run_panel
from core.event_bus import EventBus
from core.evidence.assembler import AssemblyRequest
from core.persistence.assessment_cache import (
    acquire_single_flight,
    compute_cache_key,
    compute_work_key,
)

logger = logging.getLogger(__name__)


# 12 canonical domain slugs — same list as
# tests/agents/test_domain_analyst_contract.py + the generator at
# scripts/generate_phase95_domain_analysts.py.
DOMAIN_SLUGS: list[str] = [
    "growth",
    "inflation",
    "labour",
    "housing",
    "credit",
    "monetary_policy",
    "fiscal",
    "external_sector",
    "manufacturing",
    "consumer",
    "financial_conditions",
    "commodities",
]


DEBOUNCE_SECONDS: int = 30


# ---------------------------------------------------------------------------
# SC-4 (D-04) — AssessmentCache single-flight identity constants.
#
# The D-04 single-flight identity is (domain_slug, pack.identity.state_version)
# with the run's immutable knowledge_time. `compute_work_key` also fingerprints
# the OUTPUT shape (detail_level / horizon / narrative_mode / task) so a replay
# at a different shape gets a distinct key. The deterministic ``assess()`` path
# has ONE fixed output shape, so these are constants (not per-request) — the key
# then varies ONLY on (slug, state_version, knowledge_time), exactly D-04.
# ``prompt_version`` / ``model`` mirror the deterministic manifest ``assess()``
# stamps (domain_agent.py:302-310) so the cache_key is the true anti-stale
# fingerprint (a change to the agent/definition version invalidates the entry).
# ---------------------------------------------------------------------------
_ASSESS_DETAIL_LEVEL: str = "standard"
_ASSESS_HORIZON: str = "default"
_ASSESS_NARRATIVE_MODE: str = "deterministic"
_ASSESS_TASK: str = "assess"
_ASSESS_PROMPT_VERSION: str = "deterministic-v1"
_ASSESS_MODEL: str = "deterministic"
# Operational freshness of a CACHED compute (wall-clock TTL) — independent of the
# assessment's knowledge_time as-of, which is part of the KEY, never the clock.
_ASSESS_CACHE_TTL_SECONDS: int = 300
# WR-02 single-flight LOSER re-read: when acquire_single_flight returns False a
# competing process holds the lock and is populating the cache. Poll for its put()
# a bounded number of times (total ~0.5s) before degrading to a local compute so a
# crashed holder never wedges this process.
_SINGLE_FLIGHT_WAIT_ATTEMPTS: int = 10
_SINGLE_FLIGHT_WAIT_SECONDS: float = 0.05


# ---------------------------------------------------------------------------
# Registry-driven loader (Phase 47.6 lock — no hardcoded specialist list)
# ---------------------------------------------------------------------------


def _class_name(slug: str) -> str:
    return "".join(part.title() for part in slug.split("_")) + "DomainAnalyst"


def load_analysts() -> dict[str, Any]:
    """Dynamically import and instantiate the 12 domain analyst classes.

    Returns a ``{slug: AnalystInstance}`` dict. Registry-driven — adding
    a 13th domain only requires (a) appending its slug to ``DOMAIN_SLUGS``
    and (b) shipping its ``agents/<slug>_domain_analyst`` directory; no
    edits to dispatch code (Phase 47.6 capability registry lock).
    """
    analysts: dict[str, Any] = {}
    for slug in DOMAIN_SLUGS:
        module = importlib.import_module(f"agents.{slug}_domain_analyst.agent")
        cls = getattr(module, _class_name(slug))
        analysts[slug] = cls()
    return analysts


# ---------------------------------------------------------------------------
# DomainAnalystSubscriber — debounce + idempotency + resilience
# ---------------------------------------------------------------------------


class DomainAnalystSubscriber:
    """Subscribes 12 domain analysts to MACRO_RELEASE EventBus traffic.

    Parameters
    ----------
    event_bus:
        Optional injected :class:`EventBus` (typically a stub in tests).
    analysts:
        Optional ``{slug: AnalystInstance}`` dict. If ``None`` the
        default 12 are loaded via :func:`load_analysts`.
    idempotency_store:
        Optional ``set``-like store of processed ``(event_id, snapshot_version)``
        tuples. Defaults to an in-memory ``set``. Production deployments
        may swap in a Redis-backed set for cross-restart durability.
    domain_fetcher:
        Callable ``(slug, event) -> Domain | None`` resolving the current
        Domain snapshot for a release. Wired in ``main()`` to the production
        :class:`~agents.domain_analyst_subscriber.domain_fetcher.DomainSnapshotFetcher`
        (Phase 156 / AZE-02). Optional — if ``None`` the subscriber logs the
        event without invoking analysts. A fetcher returning ``None`` (transient
        miss) leaves the idempotency/debounce slots unmarked (D-02).
    assembler:
        Optional :class:`~core.evidence.assembler.EvidencePackAssembler`. When
        supplied together with ``facet_deps`` the subscriber runs the SC-1 (D-01)
        governance path — ``assemble(AssemblyRequest) -> assess(pack) ->
        DomainAssessment`` — ALONGSIDE the unchanged legacy ``analyst.invoke``
        (both producers emit). ``None`` (default) leaves the legacy-only behaviour
        untouched (optional-DI: a missing dep degrades, never bricks).
    facet_deps:
        Optional :class:`~core.evidence.assembler.FacetDeps` (D-05 Option A —
        VM102-backed ``domain_state_reader``). Required for the governance path to
        produce a NON-empty pack; without it (or with an all-``None`` FacetDeps)
        the pack degrades honest-empty and ``assess()`` abstains.
    assessment_sink:
        Optional ``Callable[[DomainAssessment], None]`` (or
        ``Callable[[DomainAssessment, CriticVerdict], None]``) the governance path
        emits through (RESEARCH Open Q2). ``None`` (default) => a structured
        ``logger`` line carrying per-claim ``claim_id`` + ``manifest.state_version``
        + ``integrity_state`` + the panel ``verdict``. NEVER overloads the EventBus
        ``SpecialistResponse`` topic — a durable pub/sub ``EventType`` is a
        documented follow-up. SC-2 (172-05): every emit now carries the
        :class:`CriticVerdict` alongside the assessment; a single-arg sink
        (pre-172-05) is still honored (backward-compatible).
    assessment_cache:
        Optional :class:`~core.persistence.assessment_cache.AssessmentCache`
        (SC-4 / D-04). When supplied the governance path is single-flight: AFTER
        ``assemble()`` (cheap) but BEFORE ``assess()``/``run_panel()`` (expensive)
        the cache is consulted on ``work_key = (domain_slug,
        pack.identity.state_version)`` + immutable ``knowledge_time``; a HIT reuses
        the cached ``DomainAssessment`` (``assess()`` is skipped), a MISS acquires
        the Redis single-flight lock, runs ``assess()``, and populates the cache.
        ``None`` (default) => proceed WITHOUT cache (still correct — degrade-safe).
    redis_client:
        Optional Redis client for the SC-4 ``acquire_single_flight`` cross-process
        lock (``SET NX EX``). ``None`` (default, or Redis down) => proceed WITHOUT
        a lock (``acquire_single_flight`` returns ``True``) — degrade-safe, never
        bricks the compute path.
    debounce_seconds:
        Override the 30s debounce window (default :data:`DEBOUNCE_SECONDS`).
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        analysts: dict[str, Any] | None = None,
        idempotency_store: set | None = None,
        domain_fetcher: Callable[[str, EconomicEvent], Any] | None = None,
        assembler: Any | None = None,
        facet_deps: Any | None = None,
        assessment_sink: Callable[..., None] | None = None,
        assessment_cache: Any | None = None,
        redis_client: Any | None = None,
        debounce_seconds: int = DEBOUNCE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.event_bus = event_bus
        self.analysts = analysts if analysts is not None else load_analysts()
        self.processed: set = idempotency_store if idempotency_store is not None else set()
        # _last_invoke_ts is plain dict (NOT defaultdict) so missing slug ⇒
        # first invocation ⇒ debounce check skipped. Using defaultdict(float)
        # would cause a clock returning 0.0 on the first call to be wrongly
        # debounced against the 0.0 default.
        self._last_invoke_ts: dict[str, float] = {}
        self.domain_fetcher = domain_fetcher
        # SC-1 / D-01 optional-DI governance path (assemble -> assess -> sink).
        # All three guarded: the new block only runs when assembler AND facet_deps
        # are both present, so legacy-only construction is byte-for-byte unchanged.
        self.assembler = assembler
        self.facet_deps = facet_deps
        self.assessment_sink = assessment_sink
        # SC-4 / D-04 optional-DI single-flight seam (consult after assemble,
        # before assess). Both guarded: absent => proceed without cache/lock
        # (still correct — degrade-safe).
        self.assessment_cache = assessment_cache
        self.redis_client = redis_client
        self.debounce_seconds = debounce_seconds
        self._clock = clock

    # ------------------------------------------------------------------ handle
    def handle(self, event: EconomicEvent) -> None:
        """Dispatch a single EconomicEvent to the matching analysts.

        Skips events whose ``event_type != MACRO_RELEASE`` or whose
        ``payload.affected_domains`` doesn't intersect any of the 12
        domain slugs. Applies debounce + idempotency before each analyst
        invoke. One analyst raising MUST NOT break the others.
        """
        if event.event_type != EventType.MACRO_RELEASE:
            return

        affected = event.payload.get("affected_domains") or []
        if not affected:
            return
        snapshot_version = event.payload.get("snapshot_version")

        # Phase 168 (D-06a / AGV-08 / T-168-10): read the run's point-in-time
        # as-of off the inbound EconomicEvent envelope and carry it IMMUTABLY
        # down the fan-out. This async MACRO_RELEASE hop is exactly where a
        # re-mint to ``now()`` would silently introduce temporal look-ahead
        # (the "collapse to latest" pitfall) — we NEVER re-stamp here, we
        # forward ``event.knowledge_time`` verbatim. ``None`` means the event
        # predates the knowledge_time carrier (168-01), in which case the
        # downstream analyst falls back to its own as-of.
        knowledge_time = event.knowledge_time

        for slug in affected:
            analyst = self.analysts.get(slug)
            if analyst is None:
                # D-02 unknown-slug drop — a slug not in the canonical 12 is
                # logged at WARNING (not silently skipped) so a malformed /
                # drifted producer payload is visible, never fabricated.
                logger.warning(
                    "domain_analyst_subscriber: unknown domain slug %r in "
                    "affected_domains event_id=%s — dropping (not one of the "
                    "canonical 12)",
                    slug, event.event_id,
                )
                continue

            # Idempotency check — same (slug, event_id, snapshot_version) ⇒ skip.
            # Slug is part of the key so a broadcast event reaching all 12
            # analysts marks 12 separate idempotency slots, not one shared
            # slot that would suppress 11 of the 12.
            key = (slug, event.event_id, snapshot_version)
            if key in self.processed:
                logger.debug(
                    "domain_analyst_subscriber: idempotency hit "
                    "slug=%s event_id=%s snapshot_version=%s",
                    slug, event.event_id, snapshot_version,
                )
                continue

            # Debounce — same slug invoked within debounce_seconds ⇒ skip.
            # First-ever invocation for this slug is NEVER debounced.
            now = self._clock()
            last_ts = self._last_invoke_ts.get(slug)
            if last_ts is not None and now - last_ts < self.debounce_seconds:
                logger.debug(
                    "domain_analyst_subscriber: debounce skip "
                    "slug=%s event_id=%s",
                    slug, event.event_id,
                )
                continue

            try:
                domain = self._fetch_domain(slug, event)
                if domain is None:
                    # D-02 (permanent-drop fix): a transient miss (snapshot not
                    # ready yet) must NOT mark the idempotency / debounce slots,
                    # so the release is re-processed when the snapshot lands.
                    # The marking below is now gated inside the ``else`` branch.
                    logger.info(
                        "domain_analyst_subscriber: no domain payload "
                        "available slug=%s event_id=%s — logging only "
                        "(idempotency/debounce NOT marked, retry-friendly)",
                        slug, event.event_id,
                    )
                else:
                    # D-06a: forward the event's as-of onto the analyst
                    # invocation via the existing ``context`` param (all 12
                    # domain analysts accept ``context: dict | None``) — an
                    # immutable passthrough, not a fresh stamp.
                    analyst.invoke(domain, {"knowledge_time": knowledge_time})

                    # CR-01: the legacy producer has now run + emitted. Commit the
                    # idempotency/debounce marking IMMEDIATELY — before the additive
                    # governance block below — so a governance-side failure can never
                    # leave the slots unmarked and re-fire the legacy invoke on the
                    # next event of a release burst (the module docstring's "collapse
                    # to one analyst invocation" guarantee). Marking here is gated on
                    # legacy dispatch success only; a transient ``domain is None`` miss
                    # stays unmarked in the branch above (D-02 retry-friendly).
                    self.processed.add(key)
                    self._last_invoke_ts[slug] = now

                    # SC-1 (D-01): the additive governance path runs ALONGSIDE the
                    # legacy invoke above — BOTH producers emit per release per slug.
                    # It is wrapped in its OWN inner try/except (CR-01) so a failure
                    # anywhere in assemble->assess->cache->run_panel->emit degrades
                    # honest-empty (logged, no fabrication) and NEVER disturbs the
                    # legacy emit, the marking above, or the other 11 slugs.
                    # ``assess()`` is pack-sourced / LLM-free — NEVER coupled to the
                    # analyst's SpecialistResponse (engine-lock, enforced by
                    # test_domain_base_engine_lock). The pack is read from VM102 via
                    # ``facet_deps`` (D-05 Option A); a honest-empty pack
                    # (unwired/unreachable VM102) makes ``assess()`` abstain rather
                    # than fabricate. Optional-DI: skipped entirely unless both the
                    # assembler and facet_deps were injected.
                    if self.assembler is not None and self.facet_deps is not None:
                        try:
                            request = AssemblyRequest(
                                country=event.country,
                                domain_slug=slug,
                                knowledge_time=knowledge_time,
                            )
                            pack = self.assembler.assemble(request, deps=self.facet_deps)

                            # SC-4 (D-04): consult the AssessmentCache AFTER assemble()
                            # (cheap — the pack.identity.state_version is now known) but
                            # BEFORE assess()/run_panel() (the expensive work to skip).
                            # On a HIT we reuse the cached DomainAssessment; on a MISS we
                            # single-flight, run assess(), and populate. When no cache is
                            # wired the seam is skipped entirely (proceed uncached — still
                            # correct). The single-flight lock degrades safely when Redis
                            # is down (acquire_single_flight returns True — no-lock).
                            assessment = None
                            doc_id = None
                            cache_key = None
                            if self.assessment_cache is not None:
                                doc_id, cache_key = self._assessment_cache_keys(
                                    analyst, slug, pack, knowledge_time
                                )
                                assessment = self.assessment_cache.get(
                                    doc_id, request_key=cache_key
                                )

                            if assessment is None:
                                # MISS (or no cache) — acquire the cross-process
                                # single-flight lock. WR-02: HONOR the return value.
                                # ``True`` => THIS process is the lock holder: compute
                                # + populate. ``False`` => a competing process already
                                # holds the lock and is computing; do NOT double-
                                # compute/double-emit — re-read the cache (bounded
                                # wait) for the holder's put() and reuse it. Degrade-
                                # safe: if the holder never lands (crash / lock self-
                                # expiry) the bounded re-read returns None and we fall
                                # through to compute locally (assess() is
                                # deterministic — no divergence). With no Redis wired
                                # acquire_single_flight returns True (proceed w/o lock).
                                acquired = True
                                if self.assessment_cache is not None:
                                    acquired = acquire_single_flight(
                                        self.redis_client, doc_id
                                    )
                                if not acquired and self.assessment_cache is not None:
                                    assessment = self._await_cached_assessment(
                                        doc_id, cache_key
                                    )
                                if assessment is None:
                                    # Lock holder (or degrade-on-timeout) computes.
                                    # Reuse the already-loaded analyst instance
                                    # (subclasses DomainAgent) — no parallel agent set.
                                    # knowledge_time is the event's immutable as-of (no
                                    # wall-clock re-stamp — D-06a).
                                    assessment = analyst.assess(
                                        pack, knowledge_time=knowledge_time
                                    )
                                    # Only the process that actually computed
                                    # populates the cache for the single-flight losers.
                                    if self.assessment_cache is not None:
                                        valid_until = datetime.now(
                                            timezone.utc
                                        ) + timedelta(seconds=_ASSESS_CACHE_TTL_SECONDS)
                                        self.assessment_cache.put(
                                            doc_id,
                                            assessment,
                                            cache_key=cache_key,
                                            valid_until=valid_until,
                                        )

                            # SC-2 (D-02a): every DomainAssessment is adjudicated by the
                            # 5-lens panel (reject-ceiling aggregate_panel) BEFORE it is
                            # emitted — including a reused (cached) assessment, so no emit
                            # is ever ungoverned. run_panel short-circuits DOMAIN-NATIVE to
                            # a REJECT verdict WITHOUT running the lenses when the producer
                            # abstained or the pack's domain_state integrity is degraded
                            # (check_domain_vetoes) — we rely on that built-in guard, we do
                            # NOT add a parallel one. DOMAIN path only: main_loop.py's
                            # strategy critic is untouched (D-02b SPLIT).
                            verdict = run_panel(assessment, pack)
                            self._emit_assessment(assessment, verdict)
                        except Exception as gov_exc:  # noqa: BLE001 — governance is additive; never disturb legacy dispatch/marking
                            logger.exception(
                                "domain_analyst_subscriber: governance path failed "
                                "slug=%s event_id=%s: %s — legacy emit + "
                                "idempotency/debounce marking preserved "
                                "(honest-empty degrade, other slugs unaffected)",
                                slug, event.event_id, gov_exc,
                            )
            except Exception as exc:  # noqa: BLE001 — one bad analyst must not kill the rest
                logger.exception(
                    "domain_analyst_subscriber: analyst %s raised on "
                    "event %s: %s",
                    slug, event.event_id, exc,
                )
                # Intentionally do NOT mark the key — retryable failure.
                continue

    # ------------------------------------------------------------------ helpers
    def _fetch_domain(self, slug: str, event: EconomicEvent) -> Any | None:
        """Resolve the current Domain payload for ``slug``.

        Delegates to the injected ``domain_fetcher`` if provided. Wave 6
        ships without SnapshotRepository wiring — 95-13 lands the
        production fetcher. Returning ``None`` is a valid no-op (the
        subscriber logs and continues).
        """
        if self.domain_fetcher is None:
            return None
        return self.domain_fetcher(slug, event)

    def _assessment_cache_keys(
        self, analyst: Any, slug: str, pack: Any, knowledge_time: Any
    ) -> tuple[str, str]:
        """Derive the SC-4 (``work_key``/``doc_id``) + ``cache_key`` for one release.

        Both are computed from values available AFTER ``assemble()`` but BEFORE
        ``assess()`` — the pack's identity (``state_version``/``country``), the
        immutable ``knowledge_time``, and the analyst/definition version constants —
        so the cache consult never has to run the expensive assess path first.

        * ``work_key`` (returned as ``doc_id``, the identity-stable cache document id)
          is the D-04 single-flight identity: it varies ONLY on ``(slug,
          pack.identity.state_version, knowledge_time)`` because the deterministic
          ``assess()`` output shape is fixed (module constants). Two identical
          releases => the same key => a single-flight hit.
        * ``cache_key`` is the full anti-stale manifest fingerprint (mirrors the
          deterministic ``assess()`` manifest: agent/definition versions + prompt +
          model). A change to any of those invalidates the entry even on a state
          match (``AssessmentCache.is_valid`` enforces hash-match AND TTL).
        """
        state_version = pack.identity.state_version
        geography = pack.identity.country
        defn = analyst._resolve_definition()

        work_key = compute_work_key(
            agent_type=getattr(analyst, "AGENT_ID", "") or type(analyst).__name__,
            domain=slug,
            geography=geography,
            sector=None,
            state_version=state_version,
            knowledge_time=knowledge_time,
            detail_level=_ASSESS_DETAIL_LEVEL,
            horizon=_ASSESS_HORIZON,
            narrative_mode=_ASSESS_NARRATIVE_MODE,
            task=_ASSESS_TASK,
        )
        cache_key = compute_cache_key(
            agent_version=getattr(analyst, "AGENT_VERSION", "1.0.0"),
            domain_definition_version=defn.domain_definition_version,
            state_version=state_version,
            knowledge_version=defn.knowledge_version,
            feature_set_version=f"dd-{defn.domain_definition_version}",
            prompt_version=_ASSESS_PROMPT_VERSION,
            model=_ASSESS_MODEL,
            knowledge_time=knowledge_time,
        )
        return work_key, cache_key

    def _await_cached_assessment(self, doc_id: str, cache_key: str) -> Any | None:
        """WR-02 single-flight LOSER path — bounded re-read of the AssessmentCache.

        Called only when ``acquire_single_flight`` returned ``False`` (a competing
        process holds the lock and is computing+populating). Poll the cache a bounded
        number of times for the holder's ``put()`` so this process REUSES the shared
        result rather than double-computing/double-emitting — the mutual-exclusion the
        single-flight lock advertises. Returns the cached ``DomainAssessment`` on a
        hit, or ``None`` if the holder never lands within the window (crash / lock
        self-expiry); the caller then degrades by computing locally (``assess()`` is
        deterministic, so a degrade compute never diverges from the holder's result).
        """
        for _ in range(_SINGLE_FLIGHT_WAIT_ATTEMPTS):
            cached = self.assessment_cache.get(doc_id, request_key=cache_key)
            if cached is not None:
                return cached
            time.sleep(_SINGLE_FLIGHT_WAIT_SECONDS)
        return None

    def _emit_assessment(self, assessment: Any, verdict: Any = None) -> None:
        """Emit a ``DomainAssessment`` + its panel ``verdict`` (RESEARCH Open Q2).

        Uses the injected ``assessment_sink`` when present; otherwise a structured
        ``logger.info`` line carrying per-claim provenance (``claim_id``) +
        ``manifest.state_version`` + ``integrity_state`` + the SC-2 panel
        ``verdict``. This deliberately does NOT overload the EventBus
        ``SpecialistResponse`` topic (channel separation) — a durable pub/sub
        ``EventType`` is a documented follow-up.

        SC-2 (172-05): the panel ``verdict`` (ACCEPT/REFINE/REJECT) is emitted
        ALONGSIDE the assessment. A two-arg sink receives ``(assessment, verdict)``;
        a pre-172-05 single-arg sink (``Callable[[DomainAssessment], None]``) is
        still honored (backward-compatible — it just does not observe the verdict).
        """
        if self.assessment_sink is not None:
            # WR-01: detect the sink arity STRUCTURALLY (inspect.signature) rather
            # than catching TypeError from a trial two-arg call. A catch-TypeError
            # retry cannot distinguish a genuine arity mismatch (a pre-172-05
            # single-arg sink) from a TypeError raised INSIDE a two-arg sink body —
            # the latter would be silently swallowed AND cause a duplicate emit /
            # side-effect on the retry. Structural detection invokes the sink exactly
            # once with the arity it actually declares, so a TypeError from within the
            # sink body propagates honestly (and is caught by the governance-block
            # try/except in handle(), never disturbing the legacy emit — CR-01).
            sink = self.assessment_sink
            try:
                params = list(inspect.signature(sink).parameters.values())
                positional = [
                    p for p in params
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
                accepts_two = len(positional) >= 2 or any(
                    p.kind == p.VAR_POSITIONAL for p in params
                )
            except (TypeError, ValueError):
                # No introspectable signature (e.g. some C callables) — assume the
                # SC-2 two-arg contract (the current default emit shape).
                accepts_two = True
            if accepts_two:
                sink(assessment, verdict)
            else:
                # Backward-compat: a pre-172-05 single-arg sink only takes the
                # assessment (it opted into the assessment-only channel; the panel
                # verdict is simply not observed by it).
                sink(assessment)
            return
        claim_ids = [c.claim_id for c in assessment.claims]
        logger.info(
            "domain_analyst_subscriber: DomainAssessment domain=%s geography=%s "
            "state_version=%s integrity_state=%s abstention=%s knowledge_time=%s "
            "claims=%d claim_ids=%s verdict=%s",
            assessment.domain,
            assessment.geography_id,
            assessment.manifest.state_version,
            assessment.integrity_state,
            assessment.abstention_outcome,
            assessment.knowledge_time,
            len(claim_ids),
            claim_ids,
            getattr(verdict, "verdict", None),
        )


# ---------------------------------------------------------------------------
# Entrypoint — runs as a docker-compose sibling service.
# ---------------------------------------------------------------------------


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        logger.info("domain_analyst_subscriber: signal %s — shutting down.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> None:
    """Run the subscriber loop. Fail-fast on missing env vars."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # Phase 156 (AZE-02 / blocker B1): construct and inject the real
    # DomainSnapshotFetcher so the 12 analysts fire on real, validated Domain
    # data (previously domain_fetcher was omitted → None → log-and-drop).
    # Imported inside main() so the module stays import-light and the fetcher's
    # fail-fast env read only fires when the service actually starts.
    from agents.domain_analyst_subscriber.domain_fetcher import DomainSnapshotFetcher

    # Phase 172 (SC-1 / D-01): construct the governance pipeline deps and inject
    # them ALONGSIDE the legacy fetcher. Imported inside main() so the module stays
    # import-light and the VM102 client's fail-fast env read only fires on first use.
    from agents.domain_analyst_subscriber.facet_deps import build_facet_deps, probe_vm102
    from core.evidence.assembler import EvidencePackAssembler

    # EventBus constructor reads REDIS_HOST + REDIS_PORT from env with NO
    # fallback defaults — KeyError at instantiation if missing (per
    # feedback_env_driven_no_fallbacks).
    bus = EventBus()

    # D-05 Option A: build the VM102-backed FacetDeps and verify reachability from
    # THIS container before declaring the path "wired". An unreachable VM102 does
    # NOT block start-up — packs degrade honest-empty and assess() abstains (never
    # a silent empty pack shipped as wired) until VM102 env/network is fixed.
    assembler = EvidencePackAssembler()
    facet_deps = build_facet_deps()
    vm102_reachable = probe_vm102(facet_deps)
    logger.info(
        "domain_analyst_subscriber: VM102 reachability probe -> %s "
        "(reachable => real packs / real claims; unreachable => honest-empty "
        "packs, assess() abstains — Option B / follow-up).",
        vm102_reachable,
    )

    subscriber = DomainAnalystSubscriber(
        event_bus=bus,
        domain_fetcher=DomainSnapshotFetcher(),
        assembler=assembler,
        facet_deps=facet_deps,
        # assessment_sink defaults to the structured logger (_emit_assessment).
    )
    bus.subscribe(EventType.MACRO_RELEASE, subscriber.handle)

    _install_signal_handlers()
    logger.info(
        "domain_analyst_subscriber: started with %d analysts subscribed "
        "to MACRO_RELEASE.",
        len(subscriber.analysts),
    )
    try:
        bus.run()
    except KeyboardInterrupt:
        logger.info("domain_analyst_subscriber: KeyboardInterrupt — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
