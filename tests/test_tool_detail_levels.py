"""Phase 168 Plan 03 Task 2 — budgeted quant tool wrappers (scalar/struct returns).

Proves the AGV-07 / D-04 contract for the quant tool surface:
- each tool returns a ToolResultEnvelope carrying a scalar/struct payload (never a series);
- L0->L4 (COMPACT->RAW) returns STRICTLY WIDENING detail, each level within its tier cap;
- a profile cap tighter than the payload marks the envelope outcome_class "partial";
- a latest-only read with ctx.knowledge_time < now sets is_latest_only_flagged=True.

Host-clean: imports fingpt_core contracts + core.evidence.tools (pure). The VM102
quant substrate is reached through an injected typed reader seam (G10) — patched
here with a fake so the budgeted surface is tested without a live VM102.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

from core.evidence.tools import budget, quant_tools


# ---------------------------------------------------------------------------
# Fixtures — a fake typed reader (stands in for the VM102 client path, G10)
# ---------------------------------------------------------------------------


def _ctx(knowledge_time: datetime) -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        conversation_id=None,
        execution_depth=0,
        knowledge_time=knowledge_time,
    )


_NOW = datetime.now(timezone.utc)
_PAST = _NOW - timedelta(days=30)
_WINDOW_START = _NOW - timedelta(days=365 * 15)

# Phase 172-02 (SC-3): ``registry_snapshot_hash`` is now keyword-REQUIRED on every
# quant tool (the ``_UNREGISTERED_SNAPSHOT`` sentinel default was removed). Direct
# callers must supply it explicitly — these unit tests pass a fixed test hash.
_SNAP = "sha-test-quant"


class _FakeReader:
    """Typed-read seam stand-in. Returns rich scalar/struct reads (no series)."""

    def __init__(self, *, latest_only: bool = False):
        self._latest_only = latest_only

    def historical_percentile(self, series_id, *, knowledge_time=None):
        return quant_tools.PercentileRead(
            percentile=71.4,
            zscore=0.63,
            n_observations=180,
            window_start=_WINDOW_START,
            window_end=_NOW,
            distribution_summary={"p25": 40.0, "p50": 55.0, "p75": 68.0},
            latest_only=self._latest_only,
            source_generated_at=_NOW,
        )

    def change_point(self, series_id, *, knowledge_time=None):
        return quant_tools.ChangePointRead(
            change_point_count=2,
            last_change_index=142,
            last_change_at=_PAST,
            recent_change=True,
            change_indices=(88, 142),
            latest_only=self._latest_only,
            source_generated_at=_NOW,
        )

    def surprise(self, event_id, *, knowledge_time=None):
        return quant_tools.SurpriseRead(
            category="MODERATE",
            standardized_surprise=1.4,
            raw_surprise=0.3,
            reaction_strength="ELEVATED",
            latest_only=self._latest_only,
            source_generated_at=_NOW,
        )

    def lead_lag(self, series_a, series_b, *, knowledge_time=None):
        return quant_tools.CorrelationRead(
            correlation=0.62,
            best_lag=3,
            best_lag_correlation=0.71,
            direction="a_leads_b",
            latest_only=self._latest_only,
            source_generated_at=_NOW,
        )


_TOOL_CALLS = [
    ("historical_percentile", lambda t, ctx, r: t.historical_percentile(ctx, "US_CORE_CPI", reader=r, registry_snapshot_hash=_SNAP)),
    ("change_point", lambda t, ctx, r: t.change_point(ctx, "US_CORE_CPI", reader=r, registry_snapshot_hash=_SNAP)),
    ("surprise_score", lambda t, ctx, r: t.surprise_score(ctx, "US_NFP_2026_08", reader=r, registry_snapshot_hash=_SNAP)),
    ("lead_lag_correlation", lambda t, ctx, r: t.lead_lag_correlation(ctx, "US_CPI", "US_PPI", reader=r, registry_snapshot_hash=_SNAP)),
]


# ---------------------------------------------------------------------------
# Every tool returns a ToolResultEnvelope with a scalar/struct payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,call", _TOOL_CALLS, ids=[c[0] for c in _TOOL_CALLS])
def test_tool_returns_envelope_with_compact_default(name, call):
    ctx = _ctx(_NOW)
    env = call(quant_tools, ctx, _FakeReader())
    assert isinstance(env, ToolResultEnvelope)
    assert env.detail_level == "COMPACT"  # default machine-to-machine
    assert env.envelope_id == ctx.envelope_id
    assert env.knowledge_time == ctx.knowledge_time  # inherited as-of
    assert env.outcome_class == "success"
    # progressive-disclosure hints point only to wider levels
    assert env.next_detail_levels == ("STANDARD", "DETAILED", "RAW")


def test_percentile_headline_is_the_scalar_not_a_series():
    env = quant_tools.historical_percentile(
        _ctx(_NOW), "US_CORE_CPI", reader=_FakeReader(), registry_snapshot_hash=_SNAP
    )
    assert env.payload.percentile == 71.4  # a number back, never the series


# ---------------------------------------------------------------------------
# L0->L4 (COMPACT->RAW) strictly widening + each level within its cap
# ---------------------------------------------------------------------------


def test_percentile_detail_levels_strictly_widen_within_cap():
    ctx = _ctx(_NOW)
    reader = _FakeReader()
    populated: list[set[str]] = []
    for level in budget.DETAIL_TIERS:
        env = quant_tools.historical_percentile(
            ctx, "US_CORE_CPI", reader=reader, detail_level=level, registry_snapshot_hash=_SNAP
        )
        assert env.detail_level == level
        # never exceeds the tier's cap
        cap = budget.TIER_CAPS[level]
        if cap is not None:
            assert budget.estimate_tokens(env.payload) <= cap
        fields = {k for k, v in env.payload.model_dump().items() if v is not None}
        populated.append(fields)
    # strictly widening COMPACT < STANDARD < DETAILED < RAW
    assert populated[0] < populated[1] < populated[2] < populated[3]


# ---------------------------------------------------------------------------
# Budget enforcement — a profile cap tighter than the payload marks partial
# ---------------------------------------------------------------------------


def test_profile_cap_marks_envelope_partial():
    # RAW payload carries the widest struct; a tiny profile cap forces partial.
    env = quant_tools.historical_percentile(
        _ctx(_NOW), "US_CORE_CPI", reader=_FakeReader(), detail_level="RAW", profile_cap=5,
        registry_snapshot_hash=_SNAP,
    )
    assert env.outcome_class == "partial"  # visible degradation, never silent


# ---------------------------------------------------------------------------
# Latest-only look-ahead honesty (Constitution 18)
# ---------------------------------------------------------------------------


def test_latest_only_read_with_past_knowledge_time_is_flagged():
    env = quant_tools.historical_percentile(
        _ctx(_PAST), "US_CORE_CPI", reader=_FakeReader(latest_only=True), registry_snapshot_hash=_SNAP
    )
    assert env.is_latest_only_flagged is True


def test_latest_only_read_at_now_is_not_flagged():
    env = quant_tools.historical_percentile(
        _ctx(_NOW), "US_CORE_CPI", reader=_FakeReader(latest_only=True), registry_snapshot_hash=_SNAP
    )
    # knowledge_time is (approximately) now => not a look-ahead => not flagged
    assert env.is_latest_only_flagged is False


def test_point_in_time_read_is_never_flagged():
    env = quant_tools.historical_percentile(
        _ctx(_PAST), "US_CORE_CPI", reader=_FakeReader(latest_only=False), registry_snapshot_hash=_SNAP
    )
    assert env.is_latest_only_flagged is False
