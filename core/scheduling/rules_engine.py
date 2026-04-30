"""
Hybrid rules engine for Brain Layer.

Supports:
- Declarative YAML rules (80% - simple threshold conditions)
- Python hooks (20% - complex multi-signal logic)
- Priority-based evaluation order
- Cooldown tracking to prevent rapid retriggering
"""

import time
from typing import Callable


class RulesEngine:
    """
    Declarative YAML rules + Python hook fallback for complex logic.

    Rules evaluated in priority order (lower number = higher priority).
    Cooldown period prevents same rule from triggering repeatedly.
    """

    def __init__(self, rules_config: dict):
        """
        Args:
            rules_config: {
                "rules": [
                    {
                        "name": str,
                        "condition": {"field": str, "op": str, "value": any}
                                    OR {"hook": str, "params": dict},
                        "action": {"type": str, "params": dict},
                        "cooldown_seconds": int,
                        "priority": int
                    }
                ]
            }
        """
        self.rules = rules_config.get("rules", [])

        # Sort rules by priority (lower number = higher priority)
        self.rules.sort(key=lambda r: r.get("priority", 999))

        # Python hook registry
        self._hooks: dict[str, Callable] = {}

        # Cooldown tracking: {rule_name: last_triggered_timestamp}
        self._last_triggered: dict[str, float] = {}

    def register_hook(self, name: str, func: Callable) -> None:
        """
        Register Python function for complex rule logic.

        Hook signature: (context: dict, params: dict) -> bool
        """
        self._hooks[name] = func

    def evaluate(self, context: dict) -> list[dict]:
        """
        Evaluate all rules against context, return triggered actions.

        Args:
            context: Signal aggregation context (failure_rate, success_rate, etc.)

        Returns:
            List of actions: [{"type": "...", "params": {...}}, ...]
        """
        actions = []

        for rule in self.rules:
            rule_name = rule["name"]

            # Check if rule is in cooldown
            if self._is_in_cooldown(rule):
                continue

            # Evaluate condition (declarative or Python hook)
            if self._evaluate_condition(rule["condition"], context):
                # Triggered - record action and update cooldown
                actions.append(rule["action"])
                self._last_triggered[rule_name] = time.time()

        return actions

    def _evaluate_condition(self, condition: dict, context: dict) -> bool:
        """
        Evaluate condition (declarative YAML or Python hook).

        Declarative: {"field": "failure_rate", "op": ">", "value": 0.3}
        Hook: {"hook": "check_multi_signal", "params": {...}}
        """
        if "hook" in condition:
            # Complex logic — call registered Python hook
            hook_name = condition["hook"]
            if hook_name not in self._hooks:
                raise ValueError(f"Hook not registered: {hook_name}")

            return self._hooks[hook_name](context, condition.get("params", {}))

        else:
            # Simple declarative condition
            field_value = context.get(condition["field"])
            operator = condition["op"]
            threshold = condition["value"]

            if operator == ">":
                return field_value > threshold
            elif operator == "<":
                return field_value < threshold
            elif operator == "==":
                return field_value == threshold
            elif operator == ">=":
                return field_value >= threshold
            elif operator == "<=":
                return field_value <= threshold
            elif operator == "in":
                return field_value in threshold
            elif operator == "not_in":
                return field_value not in threshold
            else:
                raise ValueError(f"Unknown operator: {operator}")

    def _is_in_cooldown(self, rule: dict) -> bool:
        """Check if rule is in cooldown period."""
        rule_name = rule["name"]
        cooldown_seconds = rule.get("cooldown_seconds", 0)

        if cooldown_seconds == 0:
            return False  # No cooldown

        last_triggered = self._last_triggered.get(rule_name)
        if last_triggered is None:
            return False  # Never triggered

        elapsed = time.time() - last_triggered
        return elapsed < cooldown_seconds
