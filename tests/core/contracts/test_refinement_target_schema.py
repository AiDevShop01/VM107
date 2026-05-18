"""Phase 48 Plan 48-01 — REQ-48-D1 / D5. RefinementTarget 8-field schema + validators."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import CanonicalIssueId, RefinementTarget


def _kwargs(**overrides):
    base = dict(
        scope="STRATEGY_SPEC",
        canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR,
        target_field="features",
        issue="win rate too low",
        issue_type="STATISTICAL",
        severity="HIGH",
        suggested_change="add regime filter",
        source_critic_verdict_id="cv_001",
    )
    base.update(overrides)
    return base


def test_refinement_target_round_trip() -> None:
    """8 fields round-trip."""
    rt = RefinementTarget(**_kwargs())
    dumped = rt.model_dump()
    rehydrated = RefinementTarget.model_validate(dumped)
    assert rehydrated.scope == "STRATEGY_SPEC"
    assert rehydrated.canonical_issue_id == CanonicalIssueId.WIN_RATE_BELOW_FLOOR
    assert rehydrated.target_field == "features"
    assert rehydrated.issue == "win rate too low"
    assert rehydrated.issue_type == "STATISTICAL"
    assert rehydrated.severity == "HIGH"
    assert rehydrated.suggested_change == "add regime filter"
    assert rehydrated.source_critic_verdict_id == "cv_001"


def test_refinement_target_scope_strategy_or_code_only() -> None:
    """scope ∈ {STRATEGY_SPEC, CODE_MODULE}."""
    for s in ("STRATEGY_SPEC", "CODE_MODULE"):
        rt = RefinementTarget(**_kwargs(scope=s, target_field="features" if s == "STRATEGY_SPEC" else "code"))
        assert rt.scope == s


def test_refinement_target_scope_rejects_unknown() -> None:
    """Other scope values raise ValidationError."""
    with pytest.raises(ValidationError):
        RefinementTarget(**_kwargs(scope="HYPOTHESIS"))


def test_refinement_target_severity_high_medium_low_only() -> None:
    """severity ∈ {HIGH, MEDIUM, LOW}."""
    for s in ("HIGH", "MEDIUM", "LOW"):
        rt = RefinementTarget(**_kwargs(severity=s))
        assert rt.severity == s


def test_refinement_target_severity_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        RefinementTarget(**_kwargs(severity="CRITICAL"))


def test_refinement_target_canonical_issue_id_must_be_known_enum() -> None:
    """Unknown canonical_issue_id raises ValidationError."""
    with pytest.raises(ValidationError):
        RefinementTarget(**_kwargs(canonical_issue_id="NOT_A_REAL_ID"))


def test_refinement_target_target_field_rejects_unknown_field() -> None:
    """REQ-48-D5: target_field must be a known StrategySpec/CodeModule field name."""
    with pytest.raises(ValidationError):
        RefinementTarget(**_kwargs(target_field="this_field_does_not_exist_anywhere"))


def test_refinement_target_target_field_accepts_strategy_spec_field() -> None:
    """A real StrategySpec field is accepted (e.g., 'features', 'rules')."""
    rt = RefinementTarget(**_kwargs(scope="STRATEGY_SPEC", target_field="rules"))
    assert rt.target_field == "rules"


def test_refinement_target_target_field_accepts_code_module_field() -> None:
    """A real CodeModule field is accepted (e.g., 'tests', 'code')."""
    rt = RefinementTarget(**_kwargs(scope="CODE_MODULE", target_field="tests"))
    assert rt.target_field == "tests"
