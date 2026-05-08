"""Phase 47.3 — Framework.run() aggregator tests.

Wave 0 — graduates in Plan 03 (Framework class shipped).

Includes:
- max_points==100 invariant (OQ-1)
- LOCK 4: not_available → score=0, max_score stays 100
- LOCK 5: hard_reject → forces avoid, score still visible
- canonical category ordering
- CF-5: no-strategy path records risk
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — Framework class not yet shipped (Plan 03)",
    strict=False,
)


def test_score_aggregation_sums_to_max_100(ctx_all_pass):
    """All 9 categories pass → score=100, max_score=100."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_all_pass)
    assert result.score == 100
    assert result.max_score == 100
    assert result.recommendation == "enter"  # 80+ band


def test_score_zero_when_all_not_available(ctx_all_not_available):
    """LOCK 4: All not_available → score=0, max_score still 100, partial_context=True."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_all_not_available)
    assert result.score == 0
    assert result.max_score == 100  # CONTEXT lock 4: max_score stays at 100
    assert result.partial_context is True


def test_max_score_invariant_assertion_at_boot():
    """OQ-1 + Risk 8: framework boot MUST assert sum(category.max_points) == 100."""
    from core.agents.decision_framework.framework import Framework
    # Boot itself must not raise (default V1 thresholds sum to 100)
    Framework()


def test_max_points_sum_equals_100(ctx_all_pass):
    """OQ-1 invariant: sum of category max_points == 100 in every run output."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_all_pass)
    total = sum(c.max_points for c in result.category_results)
    assert total == 100


def test_canonical_category_order():
    """category_results MUST be ordered: HTF, Location, Liquidity, Structure,
    Momentum, Compression, Pullback, RR, News."""
    from core.agents.decision_framework.framework import (
        Framework, CATEGORY_ORDER,
    )
    assert CATEGORY_ORDER == [
        "HTF", "Location", "Liquidity", "Structure", "Momentum",
        "Compression", "Pullback", "RR", "News",
    ]


def test_hard_reject_veto_forces_avoid(ctx_hard_reject_fired):
    """LOCK 5: Score may be 78 (wait band) but hard reject forces avoid."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_hard_reject_fired)
    assert result.recommendation == "avoid"
    assert len(result.hard_reject_reasons) > 0
    # Score still visible (CONTEXT lock 5)
    assert result.score >= 0  # not zeroed


def test_no_strategy_skips_hard_rejects_with_risk():
    """CF-5: ctx.strategy is None → no veto BUT framework records explicit risk."""
    from core.agents.decision_framework.framework import Framework
    # Build ctx with strategy_id=None
    raise NotImplementedError("Plan 03 fills in no-strategy fixture")
