"""Phase 172 Plan 05 Task 3 — SC-2 (D-02a) panel-before-emit splice test.

Drives a synthetic ``MACRO_RELEASE`` through ``DomainAnalystSubscriber.handle`` and
proves the SC-2 observable signal: EVERY emitted ``DomainAssessment`` is adjudicated by
the 5-lens ``run_panel`` (reject-ceiling ``aggregate_panel``) BEFORE it leaves — the
emit carries a ``CriticVerdict`` (ACCEPT/REFINE/REJECT) alongside the assessment, so no
governance output is ever ungoverned.

Two cases:
  * WIRED pack (``stub_facet_deps`` — real ``state_version``, NEUTRAL integrity): the
    producer does NOT abstain, so ``run_panel`` runs the five lenses and returns an
    aggregate verdict whose label is one of ACCEPT/REFINE/REJECT.
  * DEGRADED pack (all-``None`` ``FacetDeps`` — honest-empty -> ``assess()`` abstains):
    ``run_panel`` SHORT-CIRCUITS domain-native (``check_domain_vetoes``) to a REJECT
    verdict WITHOUT running any lens. We assert the short-circuit signature (the
    ``scv-panel-abstain-`` verdict id + the "short-circuit" rationale) — i.e. 0 lenses
    run — rather than a parallel guard, proving we rely on the panel's built-in veto.

DOMAIN path only: ``core/agents/refinement_orchestrator/main_loop.py`` is NOT touched
(D-02b SPLIT — the strategy loop keeps its single ``run_critic``).

Hermetic: no live VM102 (the ``stub_facet_deps`` supplies the envelope), no Mongo/Redis.
The analyst is a real ``GrowthDomainAnalyst`` (real ``assess`` -> real templated claims,
real lens inputs) with ``invoke`` spied so the legacy path fires WITHOUT needing a heavy
``extra="forbid"`` ``Domain``.
"""
from __future__ import annotations

from agents.domain_analyst_subscriber.subscriber import DomainAnalystSubscriber
from agents.growth_domain_analyst.agent import GrowthDomainAnalyst
from core.contracts.schemas import CriticVerdict
from core.evidence.assembler import EvidencePackAssembler, FacetDeps

from tests.agents.conftest import MACRO_RELEASE_SLUG


class _SpyAnalyst(GrowthDomainAnalyst):
    """Real ``GrowthDomainAnalyst`` (real ``assess``) with ``invoke`` spied.

    The Wave-0 fixture feeds a lightweight ``_DomainStandin`` (not a heavy ``Domain``)
    into ``invoke``; overriding ``invoke`` records the call rather than running the real
    narrative composer. ``assess`` is inherited unchanged (pack-sourced), so the panel
    fans over a genuinely real assessment.
    """

    def __init__(self) -> None:
        super().__init__()
        self.invoke_calls: list = []

    def invoke(self, domain, context=None):  # type: ignore[override]
        self.invoke_calls.append((domain, context))
        return None


def test_every_emit_carries_a_panel_verdict(
    macro_release_event, stub_domain_fetcher, stub_facet_deps
):
    """SC-2 (D-02a): a wired MACRO_RELEASE emits a DomainAssessment adjudicated by the
    5-lens panel — the emit carries a CriticVerdict (ACCEPT/REFINE/REJECT)."""
    spy = _SpyAnalyst()
    captured: list = []

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=EvidencePackAssembler(),
        facet_deps=stub_facet_deps,
        # Two-arg sink: SC-2 emits (assessment, verdict) together.
        assessment_sink=lambda assessment, verdict: captured.append(
            (assessment, verdict)
        ),
    )

    subscriber.handle(macro_release_event)

    # Legacy invoke still fires (D-01 both-producers), independent of the panel.
    assert spy.invoke_calls, "legacy analyst.invoke did not fire (D-01 both-producers)"

    # Exactly one governance emit, and it carries BOTH the assessment and the verdict.
    assert len(captured) == 1, "governance path emitted exactly one adjudicated result"
    assessment, verdict = captured[0]

    # SC-2: the emit carries a real, fully-populated CriticVerdict.
    assert isinstance(verdict, CriticVerdict), "emit did not carry a CriticVerdict"
    assert verdict.verdict in {"ACCEPT", "REFINE", "REJECT"}

    # The wired pack does NOT abstain (real claims) -> the lenses actually ran, so this
    # is NOT the domain-native short-circuit path.
    assert assessment.abstention_outcome is None, "wired pack must not abstain"
    assert not (verdict.source_critic_verdict_id or "").startswith(
        "scv-panel-abstain-"
    ), "wired (non-abstaining) pack must NOT take the 0-lens short-circuit path"


def test_degraded_pack_short_circuits_reject_zero_lenses(
    macro_release_event, stub_domain_fetcher
):
    """SC-2 (D-02a): an all-None FacetDeps -> honest-empty pack -> assess() abstains ->
    run_panel SHORT-CIRCUITS to a REJECT verdict WITHOUT running any lens
    (check_domain_vetoes). Proves the degraded-emit is still adjudicated (never
    ungoverned) via the panel's built-in veto — no parallel guard."""
    spy = _SpyAnalyst()
    captured: list = []

    subscriber = DomainAnalystSubscriber(
        analysts={MACRO_RELEASE_SLUG: spy},
        domain_fetcher=stub_domain_fetcher,
        assembler=EvidencePackAssembler(),
        facet_deps=FacetDeps(),  # unwired -> every facet UNAVAILABLE (honest-empty)
        assessment_sink=lambda assessment, verdict: captured.append(
            (assessment, verdict)
        ),
    )

    subscriber.handle(macro_release_event)

    assert len(captured) == 1
    assessment, verdict = captured[0]

    # The honest-empty pack made assess() abstain — the precondition for the veto.
    assert assessment.abstention_outcome is not None, "degraded pack must abstain"

    # SC-2 short-circuit REJECT with 0 lenses run (the domain-native veto path).
    assert isinstance(verdict, CriticVerdict)
    assert verdict.verdict == "REJECT", "abstained pack must yield a REJECT verdict"
    assert (verdict.source_critic_verdict_id or "").startswith(
        "scv-panel-abstain-"
    ), "expected the 0-lens domain-native short-circuit verdict id"
    assert "short-circuit" in verdict.rationale.lower(), (
        "expected the short-circuit rationale (the five lenses were not run)"
    )
