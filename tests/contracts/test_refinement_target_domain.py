"""Phase 170 Plan 01 — RefinementTarget domain-critique construct regression (Pitfall 1).

`RefinementTarget` was authored in Phase 48 strategy-shaped in THREE fields — `scope`
(a strategy `Literal`), `canonical_issue_id` (a 15-value strategy/backtest `StrEnum`), and
`target_field` (a validator whose vocabulary is `StrategySpec ∪ CodeModule ∪ metrics.*`).
A domain-critique target fails validation on ALL THREE unless each is additively widened.

This regression proves a domain-scoped `RefinementTarget` constructs end-to-end while the
existing strategy path is un-regressed and `extra="forbid"` is preserved (D-06, D-07).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.contracts.schemas import CanonicalIssueId, RefinementTarget


def _kwargs(**overrides):
    """Minimal valid RefinementTarget kwargs; override per-behavior."""
    base = dict(
        scope="STRATEGY_SPEC",
        canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
        target_field="features",
        issue="placeholder issue",
        issue_type="ROBUSTNESS",
        severity="HIGH",
        suggested_change="placeholder change",
        source_critic_verdict_id="cv_test_0001",
    )
    base.update(overrides)
    return base


# --- Behavior 1: a DOMAIN_ASSESSMENT-scoped target constructs -------------------


def test_domain_assessment_scope_constructs():
    rt = RefinementTarget(
        **_kwargs(
            scope="DOMAIN_ASSESSMENT",
            canonical_issue_id=CanonicalIssueId.MECHANISM_UNREGISTERED,
            target_field="claims",
        )
    )
    assert rt.scope == "DOMAIN_ASSESSMENT"
    assert rt.canonical_issue_id == CanonicalIssueId.MECHANISM_UNREGISTERED
    assert rt.target_field == "claims"


def test_domain_assessment_scope_accepts_dotted_claims_index():
    rt = RefinementTarget(
        **_kwargs(
            scope="DOMAIN_ASSESSMENT",
            canonical_issue_id=CanonicalIssueId.EVIDENCE_UNSUPPORTED,
            target_field="claims.0",
        )
    )
    assert rt.target_field == "claims.0"


# --- Behavior 2: a CLAIM-scoped target constructs on claim/assessment fields ----


@pytest.mark.parametrize(
    "target_field,issue_id",
    [
        ("invalidation_conditions", CanonicalIssueId.NO_INVALIDATION_CONDITION),
        ("integrity_state", CanonicalIssueId.MODEL_DEGRADING),
    ],
)
def test_claim_scope_constructs(target_field, issue_id):
    rt = RefinementTarget(
        **_kwargs(scope="CLAIM", canonical_issue_id=issue_id, target_field=target_field)
    )
    assert rt.scope == "CLAIM"
    assert rt.target_field == target_field


# --- Behavior 3: the existing strategy path is un-regressed ---------------------


def test_strategy_spec_scope_still_constructs():
    rt = RefinementTarget(
        **_kwargs(
            scope="STRATEGY_SPEC",
            canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
            target_field="features",
        )
    )
    assert rt.scope == "STRATEGY_SPEC"
    assert rt.target_field == "features"


def test_strategy_metrics_dotted_path_still_constructs():
    rt = RefinementTarget(
        **_kwargs(
            scope="STRATEGY_SPEC",
            canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR,
            target_field="metrics.win_rate",
        )
    )
    assert rt.target_field == "metrics.win_rate"


# --- Behavior 4: a domain scope with a non-domain field still raises ------------


def test_domain_scope_rejects_unknown_target_field():
    with pytest.raises(ValidationError):
        RefinementTarget(
            **_kwargs(
                scope="DOMAIN_ASSESSMENT",
                canonical_issue_id=CanonicalIssueId.MECHANISM_UNREGISTERED,
                target_field="not_a_real_assessment_field",
            )
        )


def test_strategy_scope_rejects_domain_only_field():
    # A DomainAssessment-only field must NOT validate under a strategy scope
    # (vocabulary discipline stays scope-partitioned).
    with pytest.raises(ValidationError):
        RefinementTarget(
            **_kwargs(
                scope="STRATEGY_SPEC",
                canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
                target_field="claims",
            )
        )


# --- Behavior 5: extra="forbid" preserved --------------------------------------


def test_unknown_top_level_key_still_raises():
    with pytest.raises(ValidationError):
        RefinementTarget(
            **_kwargs(
                scope="DOMAIN_ASSESSMENT",
                canonical_issue_id=CanonicalIssueId.MECHANISM_UNREGISTERED,
                target_field="claims",
            ),
            is_stalling=True,  # not a declared field -> extra="forbid" must reject
        )


# --- Enum governance: the 15 original strategy members remain -------------------


def test_original_canonical_issue_ids_preserved():
    original = {
        "SAMPLE_SIZE_TOO_SMALL",
        "REGIME_CONCENTRATION_HIGH",
        "PARAMETER_SENSITIVITY_HIGH",
        "WIN_RATE_BELOW_FLOOR",
        "MAX_DRAWDOWN_NEAR_FLOOR",
        "PROFIT_FACTOR_NEAR_FLOOR",
        "CONFIRMATION_BARS_INSUFFICIENT",
        "STOP_WIDTH_TOO_TIGHT",
        "STOP_WIDTH_TOO_WIDE",
        "EXIT_TIMING_DELAYED",
        "ENTRY_FILTER_TOO_LOOSE",
        "ENTRY_FILTER_TOO_STRICT",
        "OVERFIT_SIGNATURE",
        "REGIME_FRAGILITY",
        "EXPECTANCY_UNSTABLE",
    }
    members = {m.value for m in CanonicalIssueId}
    assert original.issubset(members), original - members
