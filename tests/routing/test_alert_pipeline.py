"""
Alert pipeline tests — covers ROUTER-ALERTS-01.

Tests verify the deterministic multi-threshold × multi-sink × multi-scope
alert pipeline defined in CONTEXT.md and implemented in core/routing/alert_pipeline.py.

Sink matrix (LOCKED):
    50%  → stdout + mongo (no brain_signal, no external)
    80%  → stdout + mongo + brain_signal (no external)
    100% → stdout + mongo + brain_signal + external

Per-task verification commands:
    pytest tests/routing/test_alert_pipeline.py -x -q
    pytest tests/routing/test_alert_pipeline.py::test_50pct_alert -x -q
    pytest tests/routing/test_alert_pipeline.py::test_100pct_all_sinks -x -q
"""
from core.routing.alert_pipeline import AlertPipeline, ExternalNotifier


def _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger):
    """Helper: build AlertPipeline with stub dependencies."""
    return AlertPipeline(mock_mongo, mock_signal_accumulator, ExternalNotifier(), mock_logger)


# ---------------------------------------------------------------------------
# Threshold × Sink matrix
# ---------------------------------------------------------------------------

def test_50pct_alert(mock_mongo, mock_signal_accumulator, mock_logger):
    """50% threshold: stdout JSON + MongoDB fire; Brain signal + external do NOT fire."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    events = p.evaluate("goal", "g1", spent=2.5, max_usd=5.0)
    assert len(events) == 1
    assert events[0].threshold == "50pct"
    assert events[0].scope == "goal"
    assert events[0].goal_id == "g1"

    fired = p.fire(events[0])
    assert "stdout" in fired.sinks_fired
    assert "mongo" in fired.sinks_fired
    assert "brain_signal" not in fired.sinks_fired
    assert "external" not in fired.sinks_fired


def test_80pct_three_sinks(mock_mongo, mock_signal_accumulator, mock_logger):
    """80% threshold: stdout + MongoDB + Brain cost_pressure signal fire; external does NOT."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    events = p.evaluate("goal", "g1", spent=4.0, max_usd=5.0)
    assert events[0].threshold == "80pct"

    fired = p.fire(events[0])
    assert {"stdout", "mongo", "brain_signal"} <= set(fired.sinks_fired)
    assert "external" not in fired.sinks_fired

    # Brain signal emitted with correct type and payload
    assert mock_signal_accumulator.emit_signal.call_count == 1
    sig = mock_signal_accumulator.emit_signal.call_args.args[0]
    assert sig.type == "cost_pressure"
    assert sig.payload["scope"] == "goal"
    assert sig.confidence == 1.0


def test_100pct_all_sinks(mock_mongo, mock_signal_accumulator, mock_logger):
    """100% threshold: all 4 sinks fire (stdout + MongoDB + Brain signal + external)."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    events = p.evaluate("goal", "g1", spent=5.0, max_usd=5.0)
    assert events[0].threshold == "100pct"

    fired = p.fire(events[0])
    assert {"stdout", "mongo", "brain_signal", "external"} == set(fired.sinks_fired)


def test_below_50_no_event(mock_mongo, mock_signal_accumulator, mock_logger):
    """Below all thresholds: evaluate returns empty list."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    events = p.evaluate("goal", "g1", spent=0.4, max_usd=5.0)
    assert events == []


# ---------------------------------------------------------------------------
# Per-goal threshold overrides
# ---------------------------------------------------------------------------

def test_per_goal_threshold_override(mock_mongo, mock_signal_accumulator, mock_logger):
    """Per-goal alert_overrides apply custom threshold percentages."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    # 3.75 / 5.0 = 75% — with warn_pct=0.75 this hits the warn (50pct label)
    events = p.evaluate(
        "goal", "execution_goal_001", spent=3.75, max_usd=5.0,
        custom_overrides={"warn_pct": 0.75, "critical_pct": 0.9},
    )
    assert len(events) == 1
    assert events[0].threshold == "50pct"  # warn level → labeled "50pct"

    # 4.5 / 5.0 = 90% — with critical_pct=0.9 this hits the action (80pct label)
    events2 = p.evaluate(
        "goal", "execution_goal_001", spent=4.5, max_usd=5.0,
        custom_overrides={"warn_pct": 0.75, "critical_pct": 0.9},
    )
    assert events2[0].threshold == "80pct"


# ---------------------------------------------------------------------------
# Scope matrix
# ---------------------------------------------------------------------------

def test_per_agent_type_scope(mock_mongo, mock_signal_accumulator, mock_logger):
    """agent_type scope: AlertEvent has correct scope + agent_type; goal_id is None."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    events = p.evaluate("agent_type", "agent_zero", spent=8.0, max_usd=10.0)
    assert events[0].scope == "agent_type"
    assert events[0].agent_type == "agent_zero"
    assert events[0].goal_id is None


def test_system_wide_scope(mock_mongo, mock_signal_accumulator, mock_logger):
    """system scope: AlertEvent has correct scope; goal_id + agent_type are None."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    # 80% system-wide spend
    events = p.evaluate("system", None, spent=80.0, max_usd=100.0)
    assert events[0].scope == "system"
    assert events[0].goal_id is None
    assert events[0].agent_type is None

    # Brain signal source should be "system" for system-scope alerts
    p.fire(events[0])
    sig = mock_signal_accumulator.emit_signal.call_args.args[0]
    assert sig.source == "system"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unconstrained_max_returns_no_events(mock_mongo, mock_signal_accumulator, mock_logger):
    """No budget set (max_usd=inf or max_usd=0): evaluate returns empty list."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    assert p.evaluate("goal", "g1", spent=999.0, max_usd=float("inf")) == []
    assert p.evaluate("goal", "g1", spent=999.0, max_usd=0.0) == []


def test_evaluate_and_fire_returns_fired_events(mock_mongo, mock_signal_accumulator, mock_logger):
    """evaluate_and_fire convenience wrapper returns events with sinks_fired populated."""
    p = _make_pipeline(mock_mongo, mock_signal_accumulator, mock_logger)

    results = p.evaluate_and_fire("goal", "g1", spent=4.0, max_usd=5.0)
    assert len(results) == 1
    assert "stdout" in results[0].sinks_fired
    assert "mongo" in results[0].sinks_fired
