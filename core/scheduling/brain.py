"""
Brain Layer orchestrator for goal-driven execution.

The Brain is a deterministic state aggregator that:
- Aggregates signals from tasks/agents
- Evaluates rules to determine system behavior
- Updates behavioral mode via hysteresis controller
- Computes global confidence via EMA scorer
- Emits scheduler_control (policy constraints + weights)

Brain is NOT an LLM, NOT an agent. It's a deterministic controller.
"""

import time
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from core.scheduling.enums import BehavioralMode, ResourcePolicy
from core.scheduling.hysteresis import HysteresisController
from core.scheduling.confidence import ConfidenceScorer
from core.scheduling.signals import Signal, SignalAccumulator
from core.scheduling.rules_engine import RulesEngine


class SchedulerControl(BaseModel):
    """
    Frozen policy emitted by Brain to control Scheduler behavior.

    Brain defines WHAT is allowed/preferred.
    Scheduler decides WHAT actually runs.
    """
    model_config = ConfigDict(frozen=True)

    # Hard constraints (Scheduler MUST obey)
    max_concurrent_tasks: int
    max_cost_per_cycle: float
    max_tokens_per_cycle: int
    blocked_goal_ids: list[str] = Field(default_factory=list)

    # Soft weights (Scheduler MAY use for scoring)
    priority_weights: dict[str, float]  # {P1: 4.0, P2: 2.0, P3: 1.0, P4: 0.5}
    goal_priority_overrides: dict[str, float] = Field(default_factory=dict)  # {goal_id: multiplier}

    # Policy controls
    expansion_policy: str  # "enabled" | "disabled"
    preemption_enabled: bool
    preemption_threshold: float
    max_preemptions_per_cycle: int
    aging_enabled: bool
    aging_factor: float  # Global aging multiplier


class BrainState(BaseModel):
    """
    Brain state representation.

    Includes mode, resource policy, scheduler control, confidence, and system state.
    """
    mode: BehavioralMode
    resource_policy: ResourcePolicy
    scheduler_control: SchedulerControl
    confidence_global: float
    mode_control: dict[str, Any]  # last_changed_at, min_hold_seconds, confirmation_counter, pending_mode
    system_state: dict[str, Any]  # redis_available, mongodb_healthy, initialized_from


class BrainLayer:
    """
    Deterministic Brain Layer orchestrator.

    Coordinates:
    - HysteresisController for mode transitions
    - ConfidenceScorer for global confidence
    - RulesEngine for rule evaluation
    - SignalAccumulator for hot signal collection
    """

    def __init__(
        self,
        mode: BehavioralMode,
        resource_policy: ResourcePolicy,
        hysteresis: HysteresisController,
        confidence_scorer: ConfidenceScorer,
        rules_engine: RulesEngine,
        signal_accumulator: SignalAccumulator,
        scheduler_control: SchedulerControl,
        system_state: dict[str, Any]
    ):
        self._mode = mode
        self._resource_policy = resource_policy
        self._hysteresis = hysteresis
        self._confidence_scorer = confidence_scorer
        self._rules_engine = rules_engine
        self._signal_accumulator = signal_accumulator
        self._scheduler_control = scheduler_control
        self._system_state = system_state

    @classmethod
    def bootstrap(cls, config: dict) -> "BrainLayer":
        """
        Bootstrap Brain from config (cold start).

        Args:
            config: {
                "mode": str,
                "resource_policy": str,
                "max_concurrent_tasks": int,
                "max_cost_per_cycle": float,
                "confirmation_cycles": int,
                "min_hold_seconds": int,
                "rules": dict (optional)
            }

        Returns:
            BrainLayer instance initialized from config
        """
        # Parse mode and resource policy
        mode = BehavioralMode(config.get("mode", "exploration"))
        resource_policy = ResourcePolicy(config.get("resource_policy", "normal"))

        # Create hysteresis controller
        hysteresis_config = {
            "confirmation_cycles": config.get("confirmation_cycles", 3),
            "min_hold_seconds": config.get("min_hold_seconds", 60)
        }
        hysteresis = HysteresisController(hysteresis_config)

        # Create confidence scorer
        confidence_scorer = ConfidenceScorer(span=20, lambda_penalty=0.5)

        # Create rules engine
        rules_config = config.get("rules", {"rules": []})
        rules_engine = RulesEngine(rules_config)

        # Create signal accumulator
        signal_accumulator = SignalAccumulator()

        # Create initial scheduler control
        scheduler_control = SchedulerControl(
            max_concurrent_tasks=config.get("max_concurrent_tasks", 5),
            max_cost_per_cycle=config.get("max_cost_per_cycle", 10.0),
            max_tokens_per_cycle=config.get("max_tokens_per_cycle", 100000),
            blocked_goal_ids=[],
            priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
            goal_priority_overrides={},
            expansion_policy="enabled",
            preemption_enabled=False,
            preemption_threshold=2.0,
            max_preemptions_per_cycle=1,
            aging_enabled=True,
            aging_factor=1.0
        )

        # System state
        system_state = {
            "redis_available": True,
            "mongodb_healthy": True,
            "initialized_from": "bootstrap"
        }

        return cls(
            mode=mode,
            resource_policy=resource_policy,
            hysteresis=hysteresis,
            confidence_scorer=confidence_scorer,
            rules_engine=rules_engine,
            signal_accumulator=signal_accumulator,
            scheduler_control=scheduler_control,
            system_state=system_state
        )

    def update_cycle(
        self,
        hot_signals: list[Signal],
        cold_signals: list[dict] | None = None
    ) -> None:
        """
        Brain update cycle: process signals, evaluate rules, update state.

        Steps:
        1. Aggregate signals into context
        2. Evaluate rules → apply actions
        3. Evaluate hysteresis → update mode
        4. Update confidence
        5. Rebuild scheduler_control

        Args:
            hot_signals: Real-time signals from tasks/agents
            cold_signals: Historical aggregates from MongoDB (optional)
        """
        # Aggregate signals into context
        context = self._aggregate_signals(hot_signals, cold_signals or [])

        # Evaluate rules
        actions = self._rules_engine.evaluate(context)

        # Apply actions
        self._apply_actions(actions, context)

        # Evaluate hysteresis (mode transition)
        signals_for_hysteresis = {
            "success_rate": context.get("success_rate", 0.5),
            "entropy": context.get("entropy", 0.5),
            "failure_rate": context.get("failure_rate", 0.0)
        }
        new_mode = self._hysteresis.evaluate(signals_for_hysteresis, time.time())
        self._mode = BehavioralMode(new_mode)

        # Update confidence (using validation signals)
        validation_result = context.get("validation_passed", True)
        contradiction_ratio = context.get("contradiction_ratio", 0.0)
        confidence = self._confidence_scorer.update(validation_result, contradiction_ratio)
        self._confidence_global = confidence

        # Rebuild scheduler_control (would apply mode-specific adjustments)
        # For now, keep existing control (detailed policy updates in future)

    def get_state(self) -> BrainState:
        """Get current brain state."""
        return BrainState(
            mode=self._mode,
            resource_policy=self._resource_policy,
            scheduler_control=self._scheduler_control,
            confidence_global=self._confidence_scorer.get_current(),
            mode_control={
                "last_changed_at": self._hysteresis.mode_entered_at,
                "min_hold_seconds": self._hysteresis.min_hold_seconds,
                "confirmation_counter": self._hysteresis.confirmation_counter,
                "pending_mode": self._hysteresis.pending_mode
            },
            system_state=self._system_state
        )

    def get_scheduler_control(self) -> SchedulerControl:
        """Get frozen scheduler control policy."""
        return self._scheduler_control

    def get_brain_context(self) -> dict[str, Any]:
        """
        Get bounded read-only context for agent task envelopes.

        Returns only mode, confidence, resource_policy — NOT raw brain_state.
        """
        return {
            "mode": self._mode.value,
            "confidence_global": self._confidence_scorer.get_current(),
            "resource_policy": self._resource_policy.value
        }

    def get_goal_brain_state(self, goal_id: str) -> dict[str, Any]:
        """
        Get per-goal facet of brain state.

        Future: Track per-goal success_rate, failure_rate, cost_efficiency.
        For now, return placeholder.
        """
        return {
            "goal_id": goal_id,
            "success_rate": 0.5,
            "failure_rate": 0.0,
            "cost_efficiency": 1.0
        }

    def _aggregate_signals(
        self,
        hot_signals: list[Signal],
        cold_signals: list[dict]
    ) -> dict[str, Any]:
        """
        Aggregate signals into context dict for rule evaluation.

        Returns:
            Context dict with aggregated metrics
        """
        # Count signal types
        total_signals = len(hot_signals)
        failures = sum(1 for s in hot_signals if s.type == "task_failure")
        successes = sum(1 for s in hot_signals if s.type == "task_result")

        # Calculate rates
        failure_rate = failures / total_signals if total_signals > 0 else 0.0
        success_rate = successes / total_signals if total_signals > 0 else 0.5

        # Entropy placeholder (would calculate from signal diversity)
        entropy = 0.5

        return {
            "failure_rate": failure_rate,
            "success_rate": success_rate,
            "entropy": entropy,
            "total_signals": total_signals,
            "validation_passed": success_rate > 0.5,
            "contradiction_ratio": 0.0  # Placeholder
        }

    def _apply_actions(self, actions: list[dict], context: dict) -> None:
        """
        Apply rule actions to update brain state.

        Actions can set mode, adjust weights, block goals, etc.
        """
        for action in actions:
            action_type = action["type"]
            params = action["params"]

            if action_type == "set_mode":
                # Mode changes go through hysteresis (not direct)
                # Just track in context for next cycle
                pass

            elif action_type == "adjust_priority_weight":
                # Update priority weights (would persist to scheduler_control)
                pass

            # Additional action types handled here
