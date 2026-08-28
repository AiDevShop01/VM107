"""Phase 170 Plan 04 — the specialized-critic panel tests.

Two concerns, one file (mirrors the plan's Task split):
  * `-k aggregate` — the PURE reject-ceiling aggregator (Task 1, `aggregate.py`):
    any REJECT -> panel REJECT; else any REFINE -> panel REFINE (union targets);
    ACCEPT iff all five ACCEPT (D-05). Critics never approve/rewrite.
  * the thin panel runner + SC#2 green gate + `-k purity` (Tasks 2-3, `panel.py`):
    five lenses fanned over one (assessment, pack); a bare-correlation "signal"
    with no registered mechanism is Causality-driven REJECT/REFINE with a
    MECHANISM_UNREGISTERED RefinementTarget (Constitution 11); transformation-pure.

No mocks (T-170-04-04): every verdict/target/assessment/pack is a real typed
object built from the Plan 01 fixtures or constructed directly.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import CanonicalIssueId, CriticVerdict, RefinementTarget


# ---------------------------------------------------------------------------
# Real typed builders (NO mocks) — construct genuine CriticVerdict/RefinementTarget.
# ---------------------------------------------------------------------------
def _make_target(
    *,
    issue_id: str = "EVIDENCE_UNSUPPORTED",
    verdict_id: str = "scv-test-0000",
) -> RefinementTarget:
    return RefinementTarget(
        scope="DOMAIN_ASSESSMENT",
        canonical_issue_id=CanonicalIssueId(issue_id),
        target_field="claims",
        issue="test-only refinement target",
        issue_type="EVIDENCE",
        severity="MEDIUM",
        suggested_change="do the thing",
        source_critic_verdict_id=verdict_id,
    )


def _make_verdict(
    label: str,
    *,
    confidence: float = 0.8,
    targets: list[RefinementTarget] | None = None,
    issue_id: str = "EVIDENCE_UNSUPPORTED",
    verdict_id: str = "scv-test-0000",
    snapshot_hash: str = "deadbeef",
) -> CriticVerdict:
    tgts = targets if targets is not None else (
        [] if label == "ACCEPT" else [_make_target(issue_id=issue_id, verdict_id=verdict_id)]
    )
    return CriticVerdict(
        verdict=label,
        confidence=confidence,
        refinement_targets=tgts,
        failure_modes=sorted({t.canonical_issue_id.value for t in tgts}),
        rationale=f"{label} for test",
        loaded_skills=[],
        source_critic_verdict_id=verdict_id,
        registry_snapshot_hash=snapshot_hash,
    )


# ===========================================================================
# Task 1 — reject-ceiling aggregator (-k aggregate)
# ===========================================================================
def test_aggregate_all_accept_yields_accept():
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [_make_verdict("ACCEPT", verdict_id=f"scv-{i}") for i in range(5)]
    panel = aggregate_panel(verdicts)

    assert isinstance(panel, CriticVerdict)
    assert panel.verdict == "ACCEPT"
    assert panel.refinement_targets == []
    assert panel.failure_modes == []
    assert panel.loaded_skills == []


def test_aggregate_reject_ceiling_one_reject_beats_four_accept():
    """Four ACCEPT + one REJECT -> REJECT — the panel cannot be talked into ACCEPT."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [_make_verdict("ACCEPT", verdict_id=f"scv-{i}") for i in range(4)]
    verdicts.append(
        _make_verdict("REJECT", issue_id="MECHANISM_UNREGISTERED", verdict_id="scv-causal")
    )
    panel = aggregate_panel(verdicts)

    assert panel.verdict == "REJECT"
    # The driving REJECT's target is carried on the panel verdict.
    assert "MECHANISM_UNREGISTERED" in panel.failure_modes
    assert any(
        t.canonical_issue_id == CanonicalIssueId.MECHANISM_UNREGISTERED
        for t in panel.refinement_targets
    )


def test_aggregate_refine_unions_all_targets():
    """Some REFINE (no REJECT) -> REFINE with the UNION of all lens RefinementTarget[]."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [
        _make_verdict("ACCEPT", verdict_id="scv-0"),
        _make_verdict("REFINE", issue_id="ALREADY_PRICED_IN", verdict_id="scv-mkt"),
        _make_verdict("REFINE", issue_id="NO_INVALIDATION_CONDITION", verdict_id="scv-risk"),
    ]
    panel = aggregate_panel(verdicts)

    assert panel.verdict == "REFINE"
    ids = {t.canonical_issue_id.value for t in panel.refinement_targets}
    assert ids == {"ALREADY_PRICED_IN", "NO_INVALIDATION_CONDITION"}
    assert set(panel.failure_modes) == {"ALREADY_PRICED_IN", "NO_INVALIDATION_CONDITION"}


def test_aggregate_reject_beats_refine():
    """REJECT dominates REFINE (reject-ceiling ordering)."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [
        _make_verdict("REFINE", issue_id="ALREADY_PRICED_IN", verdict_id="scv-mkt"),
        _make_verdict("REJECT", issue_id="MECHANISM_UNREGISTERED", verdict_id="scv-causal"),
        _make_verdict("ACCEPT", verdict_id="scv-ev"),
    ]
    panel = aggregate_panel(verdicts)
    assert panel.verdict == "REJECT"


def test_aggregate_populates_required_fields_no_validation_error():
    """The aggregate CriticVerdict constructs with ALL required fields (Pitfall 6)."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [
        _make_verdict("REJECT", verdict_id="scv-a", snapshot_hash="aaaa"),
        _make_verdict("ACCEPT", verdict_id="scv-b", snapshot_hash="bbbb"),
    ]
    panel = aggregate_panel(verdicts)

    assert panel.loaded_skills == []  # deterministic — no skills loaded
    assert isinstance(panel.registry_snapshot_hash, str) and panel.registry_snapshot_hash
    assert panel.source_critic_verdict_id  # deterministic id present
    assert isinstance(panel.failure_modes, list)
    assert 0.0 <= panel.confidence <= 1.0


def test_aggregate_confidence_is_min_over_driving_lenses():
    """Documented policy: confidence = min over the driving (strictest) lenses."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [
        _make_verdict("REJECT", confidence=0.9, verdict_id="scv-a"),
        _make_verdict("REJECT", confidence=0.6, verdict_id="scv-b"),
        _make_verdict("ACCEPT", confidence=0.99, verdict_id="scv-c"),
    ]
    panel = aggregate_panel(verdicts)
    assert panel.verdict == "REJECT"
    assert panel.confidence == pytest.approx(0.6)


def test_aggregate_is_reproducible():
    """Same inputs -> identical aggregate hash/id/verdict (pure, deterministic)."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    verdicts = [
        _make_verdict("REFINE", issue_id="ALREADY_PRICED_IN", verdict_id="scv-mkt"),
        _make_verdict("ACCEPT", verdict_id="scv-ev"),
    ]
    a = aggregate_panel(list(verdicts))
    b = aggregate_panel(list(verdicts))
    assert a.registry_snapshot_hash == b.registry_snapshot_hash
    assert a.source_critic_verdict_id == b.source_critic_verdict_id
    assert a.verdict == b.verdict


def test_aggregate_empty_raises():
    """An empty verdict list is a programming error — clear raise, never a silent stub."""
    from core.agents.specialized_critic.aggregate import aggregate_panel

    with pytest.raises(ValueError):
        aggregate_panel([])


# ===========================================================================
# Task 3 — panel runner: five lenses + SC#2 green gate + purity + short-circuit
# ===========================================================================
_EXPECTED_LENSES = {"EVIDENCE", "CAUSALITY", "MARKET", "RISK", "MODEL"}


def test_panel_registers_exactly_five_lenses(bare_correlation_assessment, minimal_evidence_pack):
    """run_panel fans EXACTLY five lenses; each returns a real CriticVerdict."""
    from core.agents.specialized_critic.base import SpecializedCritic
    from core.agents.specialized_critic.lens_config import default_lens_configs

    configs = default_lens_configs()
    assert set(configs) == _EXPECTED_LENSES
    assert len(configs) == 5

    for name, config in configs.items():
        verdict = SpecializedCritic(lens_config=config).critique(
            bare_correlation_assessment, minimal_evidence_pack
        )
        assert isinstance(verdict, CriticVerdict)
        assert verdict.verdict in {"ACCEPT", "REFINE", "REJECT"}
        assert config.lens in _EXPECTED_LENSES


def test_sc2_green_gate_bare_correlation_is_causality_rejected(
    bare_correlation_assessment, minimal_evidence_pack
):
    """SC#2 GREEN GATE (Constitution 11): a bare-correlation 'signal' with no
    registered transmission mechanism -> panel REJECT/REFINE driven by the
    Causality lens, with a MECHANISM_UNREGISTERED RefinementTarget citing the
    missing mechanism."""
    from core.agents.specialized_critic.panel import run_panel

    panel = run_panel(bare_correlation_assessment, minimal_evidence_pack)

    assert panel.verdict in {"REJECT", "REFINE"}
    mech_targets = [
        t
        for t in panel.refinement_targets
        if t.canonical_issue_id == CanonicalIssueId.MECHANISM_UNREGISTERED
    ]
    assert mech_targets, "expected a MECHANISM_UNREGISTERED RefinementTarget in the union"
    # The target's prose cites the MISSING transmission mechanism (Constitution 11).
    assert any("mechanism" in t.issue.lower() for t in mech_targets)
    assert "MECHANISM_UNREGISTERED" in panel.failure_modes


def test_panel_reject_ceiling_holds_over_causality_reject(
    bare_correlation_assessment, minimal_evidence_pack
):
    """Even though Evidence/Market/etc. may ACCEPT, the Causality REJECT holds the
    panel ceiling at REJECT (cannot be talked into ACCEPT)."""
    from core.agents.specialized_critic.panel import run_panel

    panel = run_panel(bare_correlation_assessment, minimal_evidence_pack)
    assert panel.verdict == "REJECT"


def test_panel_accept_path_supported_assessment(supported_assessment, minimal_evidence_pack):
    """A well-supported claim with a seeded mechanism -> panel ACCEPT (no REJECT/REFINE)."""
    from core.agents.specialized_critic.panel import run_panel

    panel = run_panel(supported_assessment, minimal_evidence_pack)
    assert panel.verdict == "ACCEPT"
    assert panel.refinement_targets == []
    assert panel.failure_modes == []


def test_purity_input_assessment_unchanged_after_run_panel(
    bare_correlation_assessment, minimal_evidence_pack
):
    """Transformation-purity (T-170-04-01): the input assessment is byte-identical
    after run_panel — no lens/aggregate mutates it, no ACCEPT-with-rewrite."""
    from core.agents.specialized_critic.panel import run_panel

    before = bare_correlation_assessment.model_dump(mode="json")
    panel = run_panel(bare_correlation_assessment, minimal_evidence_pack)
    after = bare_correlation_assessment.model_dump(mode="json")

    assert before == after  # input unchanged
    # The panel is a verdict only — it never returns a rewritten assessment.
    assert isinstance(panel, CriticVerdict)


def test_purity_pack_unchanged_after_run_panel(supported_assessment, minimal_evidence_pack):
    """The evidence pack is also read-only — unchanged after the panel runs."""
    from core.agents.specialized_critic.panel import run_panel

    before = minimal_evidence_pack.model_dump(mode="json")
    run_panel(supported_assessment, minimal_evidence_pack)
    after = minimal_evidence_pack.model_dump(mode="json")
    assert before == after


def test_domain_native_short_circuit_on_abstention(
    supported_assessment, minimal_evidence_pack
):
    """An assessment whose producer abstained -> panel REJECT/abstain WITHOUT a lens
    crash (domain-native short-circuit, Pitfall 2 — no backtest-gate call)."""
    from fingpt_core.contracts.assessment import AbstentionOutcome

    from core.agents.specialized_critic.panel import run_panel

    abstained = supported_assessment.model_copy(
        update={"abstention_outcome": AbstentionOutcome.STATE_STALE}
    )
    panel = run_panel(abstained, minimal_evidence_pack)

    assert panel.verdict == "REJECT"
    assert "short-circuit" in panel.rationale.lower()


def test_domain_native_short_circuit_on_degraded_integrity(
    supported_assessment, degraded_evidence_pack
):
    """A pack whose domain_state integrity is STALE -> panel REJECT (short-circuit)."""
    from core.agents.specialized_critic.panel import run_panel

    panel = run_panel(supported_assessment, degraded_evidence_pack)
    assert panel.verdict == "REJECT"
    assert panel.failure_modes == [CanonicalIssueId.MODEL_DEGRADING.value]
