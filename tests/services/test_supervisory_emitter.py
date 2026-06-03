"""SupervisoryEmitter tests — GREEN (Wave 1, Plan 01).

Replaces Wave 0 RED scaffold (74-00 Task 4 xfail stubs).

Verifies REQ-74-5:
- Deterministic 4-level trigger evaluator (passive/advisory/warning/critical)
- Per-level cooldowns: critical 60s, warning 120s, advisory 300s, passive=never-emits
- Zero LLM calls in emit() path (mock-asserted across all known LLM client classes)
- Passive level NEVER publishes to Redis (status-only — CONTEXT §20)
- Observation category='supervisory', correct severity, source_vm='VM107'
- trigger_event_id + correlation_id backref populated from TriggerEvent
- emit() returns Observation (or None when cooldown-gated)
- WORM: Observation is frozen — mutation raises TypeError/ValidationError

CONTEXT §19 trigger catalog:
  state_entered(ACTIVE_SUPERVISION) | opportunity_score_changed |
  structural_break | macro_event_in_window | price_within_X%_of_invalidation |
  manual_position_modification
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

from fingpt_core.contracts.observation import Observation
from services.supervisory_emitter import SupervisoryEmitter, TriggerEvent

# Path to the thresholds YAML shipped in this plan
THRESHOLDS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "supervisory_thresholds.yaml"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _emitter(env_overrides: dict | None = None) -> SupervisoryEmitter:
    """Create a SupervisoryEmitter with env vars set and Redis publish mocked."""
    env = {
        "VM107_SUPERVISORY_REDIS_URL": "redis://localhost:6379/0",
        "SUPERVISORY_COOLDOWN_ADVISORY_SEC": "300",
        "SUPERVISORY_COOLDOWN_WARNING_SEC": "120",
        "SUPERVISORY_COOLDOWN_CRITICAL_SEC": "60",
    }
    if env_overrides:
        env.update(env_overrides)
    return SupervisoryEmitter(threshold_config_path=THRESHOLDS_PATH, _env=env)


def _trigger(
    event_type: str,
    account_id: int = 1,
    trade_id: str | None = "T-001",
    trigger_event_id: str = "evt-001",
    correlation_id: str | None = "corr-001",
    **kwargs,
) -> TriggerEvent:
    return TriggerEvent(
        event_type=event_type,
        trigger_event_id=trigger_event_id,
        account_id=account_id,
        trade_id=trade_id,
        correlation_id=correlation_id,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4-level trigger evaluation
# ─────────────────────────────────────────────────────────────────────────────

class TestLevelEvaluation:
    """Deterministic level assignment for each trigger event type."""

    def test_state_entered_active_supervision_is_passive(self):
        """state_entered(ACTIVE_SUPERVISION) → passive (initial evaluation — CONTEXT §20)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation"):
            # passive never emits — emit() returns None
            result = emitter.emit(_trigger("state_entered(ACTIVE_SUPERVISION)"))
        # passive → None (passive never publishes — CONTEXT §20 "Status dot only / — / — / —")
        assert result is None, "Passive level must return None (never publishes to Redis)"

    def test_opportunity_score_drop_5pct_is_advisory(self):
        """5% drop → advisory (≥ threshold 5, < 15)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(_trigger("opportunity_score_changed", drop_pct=5.0))
        assert result is not None
        assert result.severity == "INFO", f"Advisory expected INFO severity, got {result.severity}"

    def test_opportunity_score_drop_20pct_is_warning(self):
        """20% drop → warning (≥ 15, < 30)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(_trigger("opportunity_score_changed", drop_pct=20.0))
        assert result is not None
        assert result.severity == "WARNING"

    def test_opportunity_score_drop_35pct_is_critical(self):
        """35% drop → critical (≥ 30)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(_trigger("opportunity_score_changed", drop_pct=35.0))
        assert result is not None
        assert result.severity == "CRITICAL"

    def test_price_within_0_05pct_of_invalidation_is_critical(self):
        """proximity_pct=0.05 → critical (≤ threshold 0.1)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("price_within_X%_of_invalidation", proximity_pct=0.05)
            )
        assert result is not None
        assert result.severity == "CRITICAL"

    def test_price_within_0_4pct_of_invalidation_is_warning(self):
        """proximity_pct=0.4 → warning (≤ 0.5, > 0.1)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("price_within_X%_of_invalidation", proximity_pct=0.4)
            )
        assert result is not None
        assert result.severity == "WARNING"

    def test_price_within_0_8pct_of_invalidation_is_advisory(self):
        """proximity_pct=0.8 → advisory (≤ 1.0, > 0.5)."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("price_within_X%_of_invalidation", proximity_pct=0.8)
            )
        assert result is not None
        assert result.severity == "INFO"

    def test_structural_break_regime_change_is_critical(self):
        """structural_break_severity=regime_change → critical."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("structural_break", structural_break_severity="regime_change")
            )
        assert result is not None
        assert result.severity == "CRITICAL"

    def test_structural_break_material_is_warning(self):
        """structural_break_severity=material → warning."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("structural_break", structural_break_severity="material")
            )
        assert result is not None
        assert result.severity == "WARNING"

    def test_structural_break_minor_is_advisory(self):
        """structural_break_severity=minor → advisory."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("structural_break", structural_break_severity="minor")
            )
        assert result is not None
        assert result.severity == "INFO"

    def test_macro_event_5min_is_warning(self):
        """Macro event ≤ 5 min → warning."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("macro_event_in_window", macro_event_minutes_to_release=5)
            )
        assert result is not None
        assert result.severity == "WARNING"

    def test_macro_event_15min_is_advisory(self):
        """Macro event 6–30 min → advisory."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(
                _trigger("macro_event_in_window", macro_event_minutes_to_release=15)
            )
        assert result is not None
        assert result.severity == "INFO"

    def test_manual_position_modification_is_advisory(self):
        """manual_position_modification → always advisory."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            result = emitter.emit(_trigger("manual_position_modification"))
        assert result is not None
        assert result.severity == "INFO"


# ─────────────────────────────────────────────────────────────────────────────
# Cooldown enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestCooldownGate:
    """Per-level cooldown enforcement."""

    def test_warning_cooldown_120s_blocks_at_90s(self):
        """Two warning events 90s apart → second is SKIPPED (cooldown 120s)."""
        emitter = _emitter()
        t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            first = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="evt-1"),
                _at=t0,
            )
            assert first is not None

            t1 = t0 + timedelta(seconds=90)
            second = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="evt-2"),
                _at=t1,
            )
        assert second is None, "Warning cooldown (120s) must block re-emit at 90s"

    def test_warning_cooldown_120s_delivers_at_130s(self):
        """Two warning events 130s apart → second DELIVERS (cooldown expired)."""
        emitter = _emitter()
        t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            first = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="evt-1"),
                _at=t0,
            )
            assert first is not None

            t2 = t0 + timedelta(seconds=130)
            third = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="evt-3"),
                _at=t2,
            )
        assert third is not None, "Warning must re-emit after 120s cooldown expires"

    def test_critical_cooldown_60s_blocks_at_30s(self):
        """Critical event at 30s → blocked (60s cooldown)."""
        emitter = _emitter()
        t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=35.0, trigger_event_id="c1"),
                _at=t0,
            )
            t_blocked = t0 + timedelta(seconds=30)
            result = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=35.0, trigger_event_id="c2"),
                _at=t_blocked,
            )
        assert result is None, "Critical cooldown (60s) must block at 30s"

    def test_advisory_cooldown_300s_blocks_at_100s(self):
        """Advisory event at 100s → blocked (300s cooldown)."""
        emitter = _emitter()
        t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            emitter.emit(
                _trigger("manual_position_modification", trigger_event_id="a1"),
                _at=t0,
            )
            t_blocked = t0 + timedelta(seconds=100)
            result = emitter.emit(
                _trigger("manual_position_modification", trigger_event_id="a2"),
                _at=t_blocked,
            )
        assert result is None, "Advisory cooldown (300s) must block at 100s"

    def test_cooldown_is_per_level_warning_does_not_block_critical(self):
        """Warning cooldown does NOT block a critical at 30s (critical has its own 60s cooldown)."""
        emitter = _emitter()
        t0 = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            # Emit a warning
            emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="w1"),
                _at=t0,
            )
            # Emit a critical 30s later — warning cooldown should NOT block it
            t_critical = t0 + timedelta(seconds=30)
            critical_result = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=35.0, trigger_event_id="c1"),
                _at=t_critical,
            )
        assert critical_result is not None, (
            "Critical must emit even when warning is in cooldown — cooldowns are per-level"
        )
        assert critical_result.severity == "CRITICAL"


# ─────────────────────────────────────────────────────────────────────────────
# Passive level — never publishes to Redis
# ─────────────────────────────────────────────────────────────────────────────

class TestPassiveLevel:
    """Passive level NEVER publishes (CONTEXT §20: 'Status dot only / — / — / —')."""

    def test_passive_never_calls_publish_observation(self):
        """state_entered(ACTIVE_SUPERVISION) → passive → publish_observation NOT called."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            result = emitter.emit(_trigger("state_entered(ACTIVE_SUPERVISION)"))
        assert result is None
        mock_pub.assert_not_called()

    def test_passive_emit_returns_none(self):
        """emit() returns None for passive level — not an Observation."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation"):
            result = emitter.emit(_trigger("state_entered(ACTIVE_SUPERVISION)"))
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Observation contract correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestObservationContract:
    """Emitted Observations conform to the fingpt_core Observation contract."""

    def test_category_is_supervisory(self):
        """category field is 'supervisory' for all non-passive emissions."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=20.0))
        assert obs is not None
        assert obs.category == "supervisory"

    def test_source_vm_is_vm107(self):
        """source_vm is 'VM107'."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=20.0))
        assert obs is not None
        assert obs.source_vm == "VM107"

    def test_trigger_event_id_backref_populated(self):
        """trigger_event_id is set from TriggerEvent.trigger_event_id."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, trigger_event_id="evt-backref-123")
            )
        assert obs is not None
        assert obs.trigger_event_id == "evt-backref-123"

    def test_correlation_id_populated_from_trigger(self):
        """correlation_id is set from TriggerEvent.correlation_id."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0, correlation_id="chain-XYZ")
            )
        assert obs is not None
        assert obs.correlation_id == "chain-XYZ"

    def test_correlation_id_falls_back_to_trigger_event_id_when_none(self):
        """When correlation_id is None in trigger, obs.correlation_id == trigger_event_id."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(
                _trigger("opportunity_score_changed", drop_pct=20.0,
                          trigger_event_id="evt-fallback", correlation_id=None)
            )
        assert obs is not None
        assert obs.correlation_id == "evt-fallback"

    def test_severity_mapping_advisory_is_info(self):
        """advisory → severity=INFO."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("manual_position_modification"))
        assert obs is not None
        assert obs.severity == "INFO"

    def test_severity_mapping_warning_is_warning(self):
        """warning → severity=WARNING."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=20.0))
        assert obs is not None
        assert obs.severity == "WARNING"

    def test_severity_mapping_critical_is_critical(self):
        """critical → severity=CRITICAL."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=35.0))
        assert obs is not None
        assert obs.severity == "CRITICAL"

    def test_trading_impact_is_true_for_critical(self):
        """critical observations have trading_impact=True."""
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=35.0))
        assert obs is not None
        assert obs.trading_impact is True

    def test_observation_is_frozen_after_emit(self):
        """Emitted Observation is frozen (WORM — never mutate)."""
        from pydantic import ValidationError
        emitter = _emitter()
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            obs = emitter.emit(_trigger("opportunity_score_changed", drop_pct=20.0))
        assert obs is not None
        with pytest.raises((ValidationError, TypeError)):
            obs.severity = "CRITICAL"  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# No LLM in emit path — critical assertion
# ─────────────────────────────────────────────────────────────────────────────

class TestNoLLMInEmitPath:
    """CONTEXT §19 lock: NO LLM call in emit() path — deterministic triggers only."""

    def _run_all_triggers(self, emitter: SupervisoryEmitter) -> None:
        """Run all 6 trigger event types through emit()."""
        triggers = [
            _trigger("state_entered(ACTIVE_SUPERVISION)"),
            _trigger("opportunity_score_changed", drop_pct=20.0),
            _trigger("structural_break", structural_break_severity="material"),
            _trigger("macro_event_in_window", macro_event_minutes_to_release=15),
            _trigger("price_within_X%_of_invalidation", proximity_pct=0.4),
            _trigger("manual_position_modification"),
        ]
        with mock.patch("services.observation_publisher.publish_observation") as mock_pub:
            mock_pub.return_value = 1
            for t in triggers:
                emitter.emit(t)

    def test_openai_not_called(self):
        """openai.AsyncClient never called during any emit()."""
        emitter = _emitter()
        with mock.patch.dict("sys.modules", {"openai": mock.MagicMock()}) as mock_modules:
            openai_mock = mock_modules["openai"]
            openai_mock.AsyncClient = mock.MagicMock()
            self._run_all_triggers(emitter)
            # If openai was imported and its client instantiated/called, that's a violation
            # We assert the module-level mock was not called as a constructor
            openai_mock.AsyncClient.assert_not_called()

    def test_anthropic_not_called(self):
        """anthropic.AsyncAnthropic never called during any emit()."""
        emitter = _emitter()
        with mock.patch.dict("sys.modules", {"anthropic": mock.MagicMock()}) as mock_modules:
            anthropic_mock = mock_modules["anthropic"]
            anthropic_mock.AsyncAnthropic = mock.MagicMock()
            self._run_all_triggers(emitter)
            anthropic_mock.AsyncAnthropic.assert_not_called()

    def test_supervisory_emitter_imports_no_llm_modules(self):
        """supervisory_emitter.py does NOT import openai, anthropic, or ModelRouter."""
        import ast
        import pathlib

        emitter_path = pathlib.Path(__file__).parent.parent.parent / "services" / "supervisory_emitter.py"
        source = emitter_path.read_text()
        tree = ast.parse(source)

        forbidden = {"openai", "anthropic", "ModelRouter", "call_llm"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod = alias.name.split(".")[0]
                        assert mod not in forbidden, (
                            f"supervisory_emitter.py imports forbidden LLM module: {alias.name!r}"
                        )
                elif node.module:
                    mod = node.module.split(".")[0]
                    assert mod not in forbidden, (
                        f"supervisory_emitter.py imports from forbidden LLM module: {node.module!r}"
                    )

    def test_observation_publisher_imports_no_llm_modules(self):
        """observation_publisher.py does NOT import openai, anthropic, or ModelRouter."""
        import ast
        import pathlib

        pub_path = pathlib.Path(__file__).parent.parent.parent / "services" / "observation_publisher.py"
        source = pub_path.read_text()
        tree = ast.parse(source)

        forbidden = {"openai", "anthropic", "ModelRouter", "call_llm"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod = alias.name.split(".")[0]
                        assert mod not in forbidden, (
                            f"observation_publisher.py imports forbidden LLM module: {alias.name!r}"
                        )
                elif node.module:
                    mod = node.module.split(".")[0]
                    assert mod not in forbidden, (
                        f"observation_publisher.py imports from forbidden LLM module: {node.module!r}"
                    )
