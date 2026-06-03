"""Supervisory AI emitter tests — RED scaffold, Wave 3 implements.

Verifies REQ-74-5:
- supervisory_emitter emits SupervisoryObservation on state_entered(ACTIVE_SUPERVISION)
- Per-level cooldowns: critical 60s, warning 120s, advisory 300s, passive=infinite
- No LLM call in emit() path (deterministic triggers only — CONTEXT §19)
- WORM output — append-only, never update
"""
import pytest

pytestmark = pytest.mark.xfail(
    strict=True, reason="Wave 3 (Plan 05) implements VM107/services/supervisory_emitter.py"
)


def test_emitter_emits_on_active_supervision_entry():
    """state_entered(ACTIVE_SUPERVISION) triggers initial supervisory evaluation + emit."""
    from services.supervisory_emitter import SupervisoryEmitter

    emitter = SupervisoryEmitter()
    observations = emitter.on_state_entered("ACTIVE_SUPERVISION", account_id=1)
    assert len(observations) >= 1, (
        "Entry into ACTIVE_SUPERVISION must trigger at least a passive observation"
    )
    assert observations[0].level in ("passive", "advisory", "warning", "critical")


def test_cooldown_respected():
    """Per-level cooldowns prevent flooding during ACTIVE_SUPERVISION."""
    from services.supervisory_emitter import SupervisoryEmitter
    from datetime import datetime, timezone, timedelta

    emitter = SupervisoryEmitter()

    # Emit a warning
    t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)
    emitter.emit(level="warning", account_id=1, at=t0, body="Opportunity score degraded")

    # Immediately try again — should be blocked by 120s cooldown
    t1 = t0 + timedelta(seconds=30)
    result = emitter.emit(level="warning", account_id=1, at=t1, body="Still degraded")
    assert result is None, "Warning cooldown (120s) must block re-emit at 30s"

    # After cooldown expires — should emit
    t2 = t0 + timedelta(seconds=121)
    result2 = emitter.emit(level="warning", account_id=1, at=t2, body="Degraded again")
    assert result2 is not None, "Warning must re-emit after 120s cooldown expires"


def test_critical_cooldown_60s():
    from services.supervisory_emitter import SupervisoryEmitter
    from datetime import datetime, timezone, timedelta

    emitter = SupervisoryEmitter()
    t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)
    emitter.emit(level="critical", account_id=1, at=t0, body="Price at invalidation")

    t_blocked = t0 + timedelta(seconds=30)
    result = emitter.emit(level="critical", account_id=1, at=t_blocked, body="Still critical")
    assert result is None, "Critical cooldown (60s) must block at 30s"


def test_advisory_cooldown_300s():
    from services.supervisory_emitter import SupervisoryEmitter
    from datetime import datetime, timezone, timedelta

    emitter = SupervisoryEmitter()
    t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)
    emitter.emit(level="advisory", account_id=1, at=t0, body="Monitor closely")

    t_blocked = t0 + timedelta(seconds=100)
    result = emitter.emit(level="advisory", account_id=1, at=t_blocked, body="Still monitoring")
    assert result is None, "Advisory cooldown (300s) must block at 100s"


def test_no_llm_in_emit_path():
    """LLM clients must NEVER be called during emit() — deterministic triggers only."""
    from services.supervisory_emitter import SupervisoryEmitter
    from unittest import mock
    from datetime import datetime, timezone

    # Mock all known LLM client classes to detect any call
    with mock.patch("services.supervisory_emitter.call_llm", side_effect=AssertionError(
        "LLM called in supervisory emit path — FORBIDDEN (CONTEXT §19)"
    )) as mock_llm:
        emitter = SupervisoryEmitter()
        emitter.emit(
            level="warning",
            account_id=1,
            at=datetime(2026, 6, 3, tzinfo=timezone.utc),
            body="Deterministic trigger",
        )
        mock_llm.assert_not_called()


def test_observation_is_frozen_after_emit():
    """Emitted observations are frozen (WORM — never mutate)."""
    from services.supervisory_emitter import SupervisoryEmitter
    from datetime import datetime, timezone
    from pydantic import ValidationError

    emitter = SupervisoryEmitter()
    obs = emitter.emit(
        level="passive",
        account_id=1,
        at=datetime(2026, 6, 3, tzinfo=timezone.utc),
        body="Monitoring",
    )
    assert obs is not None
    with pytest.raises((ValidationError, TypeError)):
        obs.level = "critical"  # type: ignore[misc]
