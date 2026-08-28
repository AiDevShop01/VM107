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
