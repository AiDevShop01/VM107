"""Phase 48 Plan 48-05 Task 5.1 — FieldMutability weight calibration.

REQ-48-D10. CONTEXT § Decision 10 maps StrategySpec fields to a 3-bucket
mutability ladder:

  IMMUTABLE_CORE  -> weight 0.5 per divergent field (HIGH severity)
  REFINABLE       -> weight 0.2 per divergent field (MEDIUM severity)
  MINOR_TUNING    -> weight 0.0                     (LOW severity, skipped
                                                     from score sum entirely)

identity_scorer reads these weights via Pydantic
``model_fields[name].json_schema_extra["mutability"]``.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import FieldMutability, StrategyFamily, StrategySpec


def _spec(
    *,
    name: str = "alpha-breakout-v1",
    features: tuple[str, ...] = ("rsi", "atr"),
    rules: tuple[str, ...] = ("if rsi>70 long",),
    timeframes: tuple[str, ...] = ("1h",),
    version: str = "1.0.0",
    strategy_family: StrategyFamily = StrategyFamily.BREAKOUT,
) -> StrategySpec:
    return StrategySpec(
        name=name,
        features=list(features),
        rules=list(rules),
        timeframes=list(timeframes),
        version=version,
        strategy_family=strategy_family,
    )


def test_immutable_core_drop_is_larger_than_minor_tuning_drop():
    """ONE IMMUTABLE_CORE field changed vs ONE MINOR_TUNING field changed.

    The IMMUTABLE_CORE change must drop score MORE.
    """
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()

    # MINOR_TUNING change: version goes 1.0.0 -> 9.9.9 (weight 0.0).
    minor_diff = _spec(version="9.9.9")
    score_minor, _ = compute_score(minor_diff, origin)

    # IMMUTABLE_CORE change: strategy_family BREAKOUT -> TREND_CONTINUATION.
    immut_diff = _spec(strategy_family=StrategyFamily.TREND_CONTINUATION)
    score_immut, _ = compute_score(immut_diff, origin)

    assert score_minor == 1.0, "MINOR_TUNING weight must be 0.0 (no score drop)"
    assert score_immut <= 0.50, f"single IMMUTABLE_CORE change must drop >= 0.5; got {1-score_immut}"
    assert score_immut < score_minor


def test_refinable_weight_is_between_immutable_and_minor():
    """REFINABLE drop (0.2) sits between IMMUTABLE_CORE (0.5) and MINOR_TUNING (0.0)."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()

    # REFINABLE change: features list differs.
    refinable_diff = _spec(features=("rsi", "atr", "ema_50"))
    score_refinable, _ = compute_score(refinable_diff, origin)

    # IMMUTABLE_CORE change: name differs.
    immut_diff = _spec(name="totally-different-name")
    score_immut, _ = compute_score(immut_diff, origin)

    # MINOR_TUNING change.
    minor_diff = _spec(version="2.5.7")
    score_minor, _ = compute_score(minor_diff, origin)

    assert score_immut < score_refinable < score_minor
    # Exact weight contract.
    assert score_refinable == pytest.approx(0.80, abs=1e-9)


def test_severity_labels_match_mutability_bucket():
    """diff_breakdown's severity must reflect FieldMutability of the field."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()
    # Single REFINABLE drift.
    refinable_diff = _spec(features=("rsi", "atr", "ema_50"))
    _, diff = compute_score(refinable_diff, origin)

    refinable_entries = [e for e in diff if e["field"] == "features"]
    assert len(refinable_entries) == 1
    assert refinable_entries[0]["severity"] == "MEDIUM"

    # Single IMMUTABLE_CORE drift.
    immut_diff = _spec(strategy_family=StrategyFamily.MEAN_REVERSION)
    _, diff = compute_score(immut_diff, origin)
    immut_entries = [e for e in diff if e["field"] == "strategy_family"]
    assert len(immut_entries) == 1
    assert immut_entries[0]["severity"] == "HIGH"


def test_minor_tuning_drift_omitted_from_diff_breakdown_or_marked_low():
    """MINOR_TUNING drift contributes ZERO weight. If included in diff, severity == LOW."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()
    minor_diff = _spec(version="2.0.0")
    score, diff = compute_score(minor_diff, origin)

    # Score must be exactly 1.0 (zero weight).
    assert score == 1.0

    # Any entries for the version field must be severity LOW + weight 0.0.
    version_entries = [e for e in diff if e["field"] == "version"]
    for entry in version_entries:
        assert entry["severity"] == "LOW"
        assert entry["weight"] == 0.0


def test_weights_aggregate_additively():
    """Two REFINABLE diffs -> 1.0 - (2 * 0.2) = 0.6."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    origin = _spec()
    two_refinable_diffs = _spec(
        features=("rsi", "atr", "ema_50"),  # REFINABLE diff #1
        rules=("if vwap_cross long",),       # REFINABLE diff #2
    )
    score, diff = compute_score(two_refinable_diffs, origin)
    assert score == pytest.approx(0.60, abs=1e-9)
    refinable_entries = [e for e in diff if e["severity"] == "MEDIUM"]
    assert len(refinable_entries) == 2


def test_field_mutability_metadata_lookup_works():
    """Sanity: every StrategySpec field's json_schema_extra carries 'mutability'.

    (or is the schema_version sentinel which has no mutability.)
    """
    for name, field in StrategySpec.model_fields.items():
        if name == "schema_version":
            continue
        extra = field.json_schema_extra or {}
        assert "mutability" in extra, f"field {name!r} missing mutability metadata"
        assert extra["mutability"] in {
            FieldMutability.IMMUTABLE_CORE.value,
            FieldMutability.REFINABLE.value,
            FieldMutability.MINOR_TUNING.value,
        }
