"""
RED scaffold for REQ-66-4 — implemented in Plan 66-07.

Tests:
- test_real_activity_vs_heartbeat_idle_never_mixed
- test_heartbeat_fires_only_when_conditions_met
- test_heartbeats_never_increment_productivity_metrics
- test_all_14_agent_ids_emit_events
- test_forbidden_phrases_never_appear
"""
import pytest

pytestmark = pytest.mark.phase_66

# 14 locked agent IDs per CONTEXT.md / DESIGN-BUNDLE.md §10
LOCKED_AGENT_IDS = [
    "macro-agent",
    "briefing-agent",
    "calendar-agent",
    "liquidity-agent",
    "readiness-agent",
    "pattern-engine",
    "attention-engine",
    "risk-agent",
    "session-agent",
    "replay-engine",
    "embeddings",
    "behavior-agent",
    "journal-agent",
    "discovery-agent",
]

FORBIDDEN_PHRASES = [
    "AI analyzing market",
    "AI thinking deeply",
    "AI is processing",
    "analyzing with AI",
    "deep AI analysis",
]


def test_real_activity_vs_heartbeat_idle_never_mixed():
    """REQ-66-4: REAL_ACTIVITY and HEARTBEAT_IDLE events have different event_type
    and are NEVER mixed — a single event cannot be both."""
    try:
        from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-07) must implement "
            f"emitters.agent_telemetry_emitter.AgentTelemetryEmitter: {exc}"
        )

    from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    from unittest.mock import MagicMock, patch

    emitter = AgentTelemetryEmitter()

    # Emit a REAL_ACTIVITY event
    real_event = emitter.emit_real_activity(
        agent_id="macro-agent",
        activity="Analyzed EURUSD breakout from overnight range",
        state="open",
    )
    assert real_event.event_type == "REAL_ACTIVITY", (
        f"emit_real_activity must produce event_type=REAL_ACTIVITY; got {real_event.event_type!r}"
    )

    # Emit a HEARTBEAT_IDLE event
    heartbeat_event = emitter.emit_heartbeat(
        agent_id="macro-agent",
        state="open",
    )
    assert heartbeat_event.event_type == "HEARTBEAT_IDLE", (
        f"emit_heartbeat must produce event_type=HEARTBEAT_IDLE; got {heartbeat_event.event_type!r}"
    )

    # They must differ
    assert real_event.event_type != heartbeat_event.event_type, (
        "REAL_ACTIVITY and HEARTBEAT_IDLE must have different event_type values"
    )


def test_heartbeat_fires_only_when_conditions_met():
    """REQ-66-4: Heartbeat fires ONLY when:
    - active operational state (pre/open/mid/close)
    - no real activity for >60s
    - agent is expected online
    """
    try:
        from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement AgentTelemetryEmitter: {exc}")

    from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta

    emitter = AgentTelemetryEmitter()
    now = datetime.now(timezone.utc)

    # Condition: agent last active 90s ago (> 60s threshold) + active state + online
    last_active = now - timedelta(seconds=90)
    should_heartbeat = emitter.should_emit_heartbeat(
        agent_id="briefing-agent",
        state="open",
        last_activity_at=last_active,
        agent_online=True,
    )
    assert should_heartbeat is True, (
        "Heartbeat should fire when agent has been idle 90s > 60s threshold"
    )

    # Condition: agent last active 30s ago (< 60s threshold) -> no heartbeat
    recent = now - timedelta(seconds=30)
    should_not_heartbeat = emitter.should_emit_heartbeat(
        agent_id="briefing-agent",
        state="open",
        last_activity_at=recent,
        agent_online=True,
    )
    assert should_not_heartbeat is False, (
        "Heartbeat must NOT fire when agent was active 30s ago (below 60s idle threshold)"
    )

    # Condition: inactive state (e.g., "offline") -> no heartbeat
    should_not_when_offline = emitter.should_emit_heartbeat(
        agent_id="briefing-agent",
        state="open",
        last_activity_at=last_active,
        agent_online=False,  # agent offline
    )
    assert should_not_when_offline is False, (
        "Heartbeat must NOT fire when agent_online=False"
    )


def test_heartbeats_never_increment_productivity_metrics():
    """REQ-66-4: HEARTBEAT_IDLE events must be skipped by the metric collector.
    Productivity/activity counts must NOT increment on heartbeat events."""
    try:
        from emitters.agent_telemetry_emitter import AgentTelemetryEmitter, MetricCollector
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 must implement AgentTelemetryEmitter and MetricCollector: {exc}"
        )

    from emitters.agent_telemetry_emitter import AgentTelemetryEmitter, MetricCollector
    from unittest.mock import MagicMock

    collector = MetricCollector()
    emitter = AgentTelemetryEmitter()

    # Record baseline metric count
    baseline = collector.get_activity_count(agent_id="risk-agent")

    # Emit a heartbeat
    heartbeat_event = emitter.emit_heartbeat(agent_id="risk-agent", state="mid")
    collector.record(heartbeat_event)

    # Metric count must NOT have changed
    after_heartbeat = collector.get_activity_count(agent_id="risk-agent")
    assert after_heartbeat == baseline, (
        f"HEARTBEAT_IDLE must not increment productivity metrics; "
        f"baseline={baseline}, after heartbeat={after_heartbeat}"
    )

    # Emit a REAL_ACTIVITY — this SHOULD increment
    real_event = emitter.emit_real_activity(
        agent_id="risk-agent",
        activity="Computed beta against DXY benchmark",
        state="mid",
    )
    collector.record(real_event)
    after_real = collector.get_activity_count(agent_id="risk-agent")
    assert after_real == baseline + 1, (
        f"REAL_ACTIVITY must increment productivity metric from {baseline} to {baseline+1}; "
        f"got {after_real}"
    )


@pytest.mark.parametrize("agent_id", LOCKED_AGENT_IDS)
def test_all_14_agent_ids_emit_at_least_one_event_per_state(agent_id):
    """REQ-66-4: All 14 locked agent IDs can emit at least one event per state per minute."""
    try:
        from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement AgentTelemetryEmitter: {exc}")

    from emitters.agent_telemetry_emitter import AgentTelemetryEmitter

    emitter = AgentTelemetryEmitter()

    for state in ("pre", "open", "mid", "close"):
        event = emitter.emit_real_activity(
            agent_id=agent_id,
            activity=f"Test activity for {agent_id} in state {state}",
            state=state,
        )
        assert event is not None, (
            f"agent_id={agent_id!r} must emit at least one event in state={state!r}"
        )
        assert event.agent_id == agent_id, (
            f"Emitted event agent_id must match; expected {agent_id!r}, got {event.agent_id!r}"
        )


def test_forbidden_phrases_never_appear():
    """REQ-66-4: Forbidden phrases NEVER appear in emitted telemetry text.
    'AI analyzing market...', 'AI thinking deeply...' etc. are prohibited."""
    try:
        from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement AgentTelemetryEmitter: {exc}")

    from emitters.agent_telemetry_emitter import AgentTelemetryEmitter
    from unittest.mock import patch

    emitter = AgentTelemetryEmitter()

    # Attempt to emit with a forbidden phrase — must be sanitized or rejected
    for phrase in FORBIDDEN_PHRASES:
        try:
            event = emitter.emit_real_activity(
                agent_id="macro-agent",
                activity=phrase,
                state="open",
            )
            # If no exception: verify the phrase was NOT passed through
            event_text = getattr(event, "activity", "") or getattr(event, "text", "")
            assert phrase not in event_text, (
                f"Forbidden phrase {phrase!r} appeared in emitted telemetry text. "
                "Plan 66-07 must sanitize or reject forbidden agent phrases."
            )
        except ValueError:
            pass  # Rejection via ValueError is also acceptable
