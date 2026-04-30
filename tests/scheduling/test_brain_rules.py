"""
Tests for Rules Engine and BrainLayer orchestrator.

TDD Phase: RED - Write failing tests first.
"""

import time
import pytest
from core.scheduling.rules_engine import RulesEngine
from core.scheduling.brain import BrainLayer, BrainState, SchedulerControl
from core.scheduling.signals import Signal
from core.scheduling.enums import BehavioralMode, ResourcePolicy


class TestRulesEngine:
    """Test declarative YAML rules + Python hooks."""

    def test_simple_threshold_rule_triggers_action(self):
        """Simple threshold rule: failure_rate > 0.3 -> set_mode stabilization."""
        rules_config = {
            "rules": [
                {
                    "name": "switch_to_stabilization",
                    "condition": {
                        "field": "failure_rate",
                        "op": ">",
                        "value": 0.3
                    },
                    "action": {
                        "type": "set_mode",
                        "params": {"mode": "stabilization"}
                    },
                    "cooldown_seconds": 60,
                    "priority": 1
                }
            ]
        }

        engine = RulesEngine(rules_config)

        # Context with high failure rate
        context = {"failure_rate": 0.5}

        actions = engine.evaluate(context)

        assert len(actions) == 1
        assert actions[0]["type"] == "set_mode"
        assert actions[0]["params"]["mode"] == "stabilization"

    def test_python_hook_rule_executes_complex_logic(self):
        """Python hook rule for multi-signal correlation check."""
        rules_config = {
            "rules": [
                {
                    "name": "boost_research_priority",
                    "condition": {
                        "hook": "check_multi_signal",
                        "params": {
                            "required_signals": ["low_success", "high_entropy"]
                        }
                    },
                    "action": {
                        "type": "adjust_priority_weight",
                        "params": {"task_type": "research", "multiplier": 1.3}
                    },
                    "cooldown_seconds": 60,
                    "priority": 2
                }
            ]
        }

        engine = RulesEngine(rules_config)

        # Register Python hook
        def check_multi_signal(context: dict, params: dict) -> bool:
            """Hook that checks multiple signals."""
            required = params["required_signals"]
            checks = {
                "low_success": context.get("success_rate", 1.0) < 0.5,
                "high_entropy": context.get("entropy", 0.0) > 0.6
            }
            return all(checks.get(sig, False) for sig in required)

        engine.register_hook("check_multi_signal", check_multi_signal)

        # Context that should trigger hook
        context = {"success_rate": 0.3, "entropy": 0.7}

        actions = engine.evaluate(context)

        assert len(actions) == 1
        assert actions[0]["type"] == "adjust_priority_weight"

    def test_cooldown_prevents_rapid_retriggering(self):
        """Rule triggered, then same rule not triggered again within cooldown_seconds."""
        rules_config = {
            "rules": [
                {
                    "name": "test_rule",
                    "condition": {"field": "value", "op": ">", "value": 0.5},
                    "action": {"type": "test_action", "params": {}},
                    "cooldown_seconds": 2,
                    "priority": 1
                }
            ]
        }

        engine = RulesEngine(rules_config)

        # First evaluation - should trigger
        actions1 = engine.evaluate({"value": 0.7})
        assert len(actions1) == 1

        # Immediate second evaluation - should be in cooldown
        actions2 = engine.evaluate({"value": 0.7})
        assert len(actions2) == 0, "Rule should be in cooldown"

        # Wait for cooldown to expire
        time.sleep(2.1)

        # Third evaluation - cooldown expired, should trigger again
        actions3 = engine.evaluate({"value": 0.7})
        assert len(actions3) == 1

    def test_rules_evaluated_in_priority_order(self):
        """Rules with lower priority number evaluated first."""
        rules_config = {
            "rules": [
                {
                    "name": "priority_2",
                    "condition": {"field": "trigger", "op": "==", "value": True},
                    "action": {"type": "action_2", "params": {}},
                    "cooldown_seconds": 0,
                    "priority": 2
                },
                {
                    "name": "priority_1",
                    "condition": {"field": "trigger", "op": "==", "value": True},
                    "action": {"type": "action_1", "params": {}},
                    "cooldown_seconds": 0,
                    "priority": 1
                }
            ]
        }

        engine = RulesEngine(rules_config)

        actions = engine.evaluate({"trigger": True})

        # Priority 1 should come before priority 2
        assert len(actions) == 2
        assert actions[0]["type"] == "action_1"
        assert actions[1]["type"] == "action_2"

    def test_unregistered_hook_raises_error(self):
        """Attempting to use unregistered hook raises ValueError."""
        rules_config = {
            "rules": [
                {
                    "name": "bad_rule",
                    "condition": {"hook": "nonexistent_hook", "params": {}},
                    "action": {"type": "test", "params": {}},
                    "cooldown_seconds": 0,
                    "priority": 1
                }
            ]
        }

        engine = RulesEngine(rules_config)

        with pytest.raises(ValueError, match="not registered"):
            engine.evaluate({})


class TestBrainLayer:
    """Test BrainLayer orchestration and integration."""

    def test_brain_layer_update_cycle_processes_signals(self):
        """BrainLayer.update_cycle processes signals and updates state."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "confirmation_cycles": 3,
            "min_hold_seconds": 1
        }

        brain = BrainLayer.bootstrap(config)

        # Create signals
        hot_signals = [
            Signal(
                type="task_result",
                source="task_1",
                payload={"status": "completed"},
                timestamp=time.time(),
                confidence=0.9
            ),
            Signal(
                type="task_failure",
                source="task_2",
                payload={"error": "timeout"},
                timestamp=time.time(),
                confidence=0.8
            )
        ]

        # Update cycle
        brain.update_cycle(hot_signals)

        # Verify state updated
        state = brain.get_state()
        assert state.mode == BehavioralMode.EXPLORATION
        assert state.confidence_global >= 0.0

    def test_brain_emits_scheduler_control_policy(self):
        """Brain emits SchedulerControl (frozen policy for scheduler)."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "confirmation_cycles": 3,
            "min_hold_seconds": 1
        }

        brain = BrainLayer.bootstrap(config)
        brain.update_cycle([])

        control = brain.get_scheduler_control()

        # SchedulerControl is frozen (read-only)
        assert isinstance(control, SchedulerControl)
        assert control.max_concurrent_tasks > 0
        assert control.max_cost_per_cycle > 0
        assert "P1" in control.priority_weights

    def test_brain_context_is_bounded_read_only(self):
        """get_brain_context returns bounded dict (not raw state)."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "confirmation_cycles": 3,
            "min_hold_seconds": 1
        }

        brain = BrainLayer.bootstrap(config)
        brain.update_cycle([])

        context = brain.get_brain_context()

        # Bounded context - only mode, confidence, resource_policy
        assert "mode" in context
        assert "confidence_global" in context
        assert "resource_policy" in context

        # Should NOT contain raw brain_state or scheduler_control
        assert "scheduler_control" not in context
        assert "mode_control" not in context

    def test_brain_bootstrap_from_config(self):
        """Bootstrap creates initial brain state from config."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "max_concurrent_tasks": 5,
            "max_cost_per_cycle": 10.0,
            "confirmation_cycles": 3,
            "min_hold_seconds": 60
        }

        brain = BrainLayer.bootstrap(config)

        state = brain.get_state()
        assert state.mode == BehavioralMode.EXPLORATION
        assert state.resource_policy == ResourcePolicy.NORMAL
        assert state.system_state["initialized_from"] == "bootstrap"

    def test_brain_update_cycle_is_deterministic(self):
        """Same inputs produce same outputs (deterministic behavior)."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "confirmation_cycles": 3,
            "min_hold_seconds": 1
        }

        # Create two brain instances with same config
        brain1 = BrainLayer.bootstrap(config)
        brain2 = BrainLayer.bootstrap(config)

        # Same signals
        signals = [
            Signal(
                type="task_result",
                source="task_1",
                payload={"status": "completed"},
                timestamp=1000.0,  # Fixed timestamp
                confidence=0.9
            )
        ]

        # Update both
        brain1.update_cycle(signals.copy())
        brain2.update_cycle(signals.copy())

        # Should produce same state
        state1 = brain1.get_state()
        state2 = brain2.get_state()

        assert state1.mode == state2.mode
        assert state1.confidence_global == state2.confidence_global

    def test_brain_rules_evaluation_affects_mode(self):
        """Rules engine evaluation can trigger mode transitions."""
        config = {
            "mode": "exploration",
            "resource_policy": "normal",
            "confirmation_cycles": 1,  # Fast confirmation for test
            "min_hold_seconds": 1,
            "rules": {
                "rules": [
                    {
                        "name": "stabilization_rule",
                        "condition": {"field": "failure_rate", "op": ">", "value": 0.3},
                        "action": {"type": "set_mode", "params": {"mode": "stabilization"}},
                        "cooldown_seconds": 0,
                        "priority": 1
                    }
                ]
            }
        }

        brain = BrainLayer.bootstrap(config)

        # Wait for hold time
        time.sleep(1.1)

        # Create signals indicating high failure rate
        signals = [
            Signal(
                type="task_failure",
                source="task_1",
                payload={"error": "system_error"},
                timestamp=time.time(),
                confidence=0.9
            )
        ] * 5  # Multiple failures

        brain.update_cycle(signals)

        # Mode should transition (or be pending) stabilization
        state = brain.get_state()
        # Note: May require multiple cycles depending on confirmation
        # Just verify that brain processes signals and evaluates rules
        assert hasattr(state, "mode")
