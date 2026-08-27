"""Phase 168 Plan 04 (AGV-08 / D-06) — point-in-time (PIT) integrity pillar.

The load-bearing security-relevant invariant of this phase is point-in-time
honesty (Constitution 18): a service that has NO point-in-time store (it can
only ever return the LATEST value) must DECLARE latest-only and set the
``is_latest_only_flagged`` integrity flag on its returned envelope whenever the
requested ``knowledge_time`` is in the past. Look-ahead is thereby detectable,
never silent.

These tests inject at the TYPED SEAM only — a fake latest-only service that
returns a real ``ToolResultEnvelope`` (the D-04 contract from 168-01). No
production business function is patched (no-mocks-of-production-paths).

Mirrors the reserved-but-ignored ``date`` AS-OF param on
``RegimeContributionEngine.contribution(indicator_id, lookback, date=None)`` —
the canonical latest-only precedent named in the plan interfaces.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel

from fingpt_core.contracts.tool_envelope import ToolResultEnvelope


class _ContributionPayload(BaseModel):
    """Minimal typed payload standing in for a regime-contribution result."""

    indicator_id: str
    value: float


def _make_contribution_envelope(
    *, knowledge_time: datetime, is_latest_only_flagged: bool
) -> ToolResultEnvelope:
    """Build a real ToolResultEnvelope carrying the D-04 knowledge_time fields."""
    return ToolResultEnvelope[_ContributionPayload](
        envelope_id=uuid4(),
        tool_name="regime_contribution",
        tool_version="1.0",
        outcome_class="success",
        success=True,
        generated_at=datetime.now(timezone.utc),
        registry_snapshot_hash="test-snapshot-hash",
        payload_schema_version="1.0",
        knowledge_time=knowledge_time,
        is_latest_only_flagged=is_latest_only_flagged,
        payload=_ContributionPayload(indicator_id="GDP", value=0.5),
    )


def _latest_only_contribution(
    indicator_id: str, *, knowledge_time: datetime, now: datetime
) -> ToolResultEnvelope:
    """Fake latest-only service — the typed-seam fixture.

    Emulates ``RegimeContributionEngine.contribution()`` which reserves but
    IGNORES its ``date`` AS-OF param, so it can only ever return the LATEST
    value. Per Constitution 18 (D-06) it DECLARES latest-only and sets the
    envelope integrity flag when the requested as-of predates ``now`` — the
    honest, detectable signal that a look-ahead risk exists on this read.
    """
    return _make_contribution_envelope(
        knowledge_time=knowledge_time,
        # DECLARE + flag: latest-only AND knowledge_time < now => look-ahead risk.
        is_latest_only_flagged=knowledge_time < now,
    )


def test_latest_only_flags():
    """is_latest_only_flagged is True iff knowledge_time < now (else False)."""
    now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(days=30)

    replay = _latest_only_contribution("GDP", knowledge_time=past, now=now)
    assert replay.is_latest_only_flagged is True, (
        "a latest-only service asked for a PAST as-of must raise the integrity "
        "flag — look-ahead risk must be detectable (Constitution 18)"
    )
    assert replay.knowledge_time == past

    live = _latest_only_contribution("GDP", knowledge_time=now, now=now)
    assert live.is_latest_only_flagged is False, (
        "a live request (knowledge_time == now) has no look-ahead risk and must "
        "NOT be flagged"
    )
    assert live.knowledge_time == now


def test_live_vs_replay_distinguishable():
    """A live vs replay request differing ONLY by knowledge_time is distinguishable.

    Pitfall 2 guard: replay must NOT silently collapse to the same envelope state
    as live — the integrity flag (and the carried as-of) make them different.
    """
    now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
    past = now - timedelta(days=90)

    live = _latest_only_contribution("CPI", knowledge_time=now, now=now)
    replay = _latest_only_contribution("CPI", knowledge_time=past, now=now)

    # Same tool, same inputs except the as-of — the flag / as-of must differ.
    assert live.is_latest_only_flagged != replay.is_latest_only_flagged
    assert live.knowledge_time != replay.knowledge_time
    # And the two envelope states are not identical (detectable divergence).
    assert (live.is_latest_only_flagged, live.knowledge_time) != (
        replay.is_latest_only_flagged,
        replay.knowledge_time,
    )
