"""
Governance matrix for Goal/Task system.

Enforces per-type creation rules, approval requirements, and active goal caps.
"""

from dataclasses import dataclass
from typing import Optional

from core.scheduling.enums import GoalType


@dataclass
class GovernanceRule:
    """Governance rule for a specific goal type."""

    goal_type: GoalType
    auto_create: bool  # Can agents create this goal type?
    auto_approve: bool  # Is approval automatic?
    max_active: int  # Maximum concurrent active goals of this type


class GovernanceMatrix:
    """
    Governance matrix enforcing per-type rules.

    Default rules per CONTEXT.md:
    - maintenance: auto_create=True, auto_approve=True, max_active=10
    - learning: auto_create=True, auto_approve=True, max_active=10
    - research: auto_create=True, auto_approve=False, max_active=5
    - execution: auto_create=False, auto_approve=False, max_active=3
    - system: auto_create=False, auto_approve=False, max_active=2
    """

    def __init__(self, rules: Optional[dict[GoalType, GovernanceRule]] = None):
        """Initialize with default or custom rules."""
        if rules is None:
            self.rules = self._default_rules()
        else:
            self.rules = rules

    @staticmethod
    def _default_rules() -> dict[GoalType, GovernanceRule]:
        """Default governance rules per CONTEXT.md."""
        return {
            GoalType.MAINTENANCE: GovernanceRule(
                goal_type=GoalType.MAINTENANCE,
                auto_create=True,
                auto_approve=True,
                max_active=10,
            ),
            GoalType.LEARNING: GovernanceRule(
                goal_type=GoalType.LEARNING,
                auto_create=True,
                auto_approve=True,
                max_active=10,
            ),
            GoalType.RESEARCH: GovernanceRule(
                goal_type=GoalType.RESEARCH,
                auto_create=True,
                auto_approve=False,
                max_active=5,
            ),
            GoalType.EXECUTION: GovernanceRule(
                goal_type=GoalType.EXECUTION,
                auto_create=False,
                auto_approve=False,
                max_active=3,
            ),
            GoalType.SYSTEM: GovernanceRule(
                goal_type=GoalType.SYSTEM,
                auto_create=False,
                auto_approve=False,
                max_active=2,
            ),
        }

    def can_create(self, goal_type: GoalType, creator: str) -> bool:
        """
        Check if creator can create a goal of this type.

        Args:
            goal_type: Type of goal to create
            creator: Creator ID (user or agent)

        Returns:
            True if creation is allowed
        """
        rule = self.rules.get(goal_type)
        if not rule:
            return False

        # For execution and system goals, auto_create is False
        # This means only humans can create them (agents cannot)
        # We detect agents vs humans by convention, but for now
        # we just use the rule's auto_create flag
        return rule.auto_create

    def requires_approval(self, goal_type: GoalType) -> bool:
        """
        Check if goal type requires approval before activation.

        Args:
            goal_type: Type of goal

        Returns:
            True if approval is required
        """
        rule = self.rules.get(goal_type)
        if not rule:
            return True  # Unknown types require approval

        return not rule.auto_approve

    def get_max_active(self, goal_type: GoalType) -> int:
        """
        Get maximum concurrent active goals for this type.

        Args:
            goal_type: Type of goal

        Returns:
            Maximum active goal count
        """
        rule = self.rules.get(goal_type)
        if not rule:
            return 0  # Unknown types not allowed

        return rule.max_active

    def validate_goal_creation(
        self, goal_type: GoalType, creator: str, current_active_count: int
    ) -> tuple[bool, Optional[str]]:
        """
        Validate goal creation against governance rules.

        Args:
            goal_type: Type of goal to create
            creator: Creator ID
            current_active_count: Current number of active goals of this type

        Returns:
            (is_valid, error_message)
        """
        if not self.can_create(goal_type, creator):
            return False, f"Creator '{creator}' cannot create {goal_type.value} goals"

        max_active = self.get_max_active(goal_type)
        if current_active_count >= max_active:
            return False, f"Maximum active {goal_type.value} goals reached ({max_active})"

        return True, None
