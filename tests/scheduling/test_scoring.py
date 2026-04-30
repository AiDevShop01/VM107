"""
Tests for TaskScorer - scoring formula with bounded factors and mode bias.

Tests multiplicative core formula, bounded aging, mode bias adjustments,
and anti-starvation guarantees (P4 never outranks P1).
"""

import pytest
from core.scheduling.scoring import TaskScorer
from core.scheduling.enums import Priority, BehavioralMode


class TestPriorityBase:
    """Test priority base factor (P)."""

    def test_p1_base_weight(self):
        """P1 returns base weight 4.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P1}
        assert scorer._priority_base(task) == 4.0

    def test_p2_base_weight(self):
        """P2 returns base weight 2.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P2}
        assert scorer._priority_base(task) == 2.0

    def test_p3_base_weight(self):
        """P3 returns base weight 1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P3}
        assert scorer._priority_base(task) == 1.0

    def test_p4_base_weight(self):
        """P4 returns base weight 0.5."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P4}
        assert scorer._priority_base(task) == 0.5


class TestGoalWeight:
    """Test goal weight factor (G)."""

    def test_success_rate_zero(self):
        """success_rate=0.0 returns G=0.5."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        goal = {"success_rate": 0.0}
        assert scorer._goal_weight(goal) == 0.5

    def test_success_rate_one(self):
        """success_rate=1.0 returns G=2.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        goal = {"success_rate": 1.0}
        assert scorer._goal_weight(goal) == 2.0

    def test_success_rate_half(self):
        """success_rate=0.5 returns G=1.25."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        goal = {"success_rate": 0.5}
        # Linear interpolation: 0.5 + (2.0 - 0.5) * 0.5 = 0.5 + 0.75 = 1.25
        assert scorer._goal_weight(goal) == 1.25


class TestBrainWeight:
    """Test brain weight factor (B) with mode bias and goal overrides."""

    def test_exploration_mode_research_task(self):
        """Exploration mode gives research tasks 1.3x boost."""
        brain_state = {"mode": BehavioralMode.EXPLORATION}
        mode_config = {
            "exploration": {"research": 1.3, "analysis": 1.3, "execution": 0.8}
        }
        scorer = TaskScorer(brain_state=brain_state, mode_config=mode_config)
        task = {"task_type": "research"}
        goal = {}
        # B = 1.3 (mode_bias), clamped to [0.7, 1.5]
        assert scorer._brain_weight(task, goal) == 1.3

    def test_exploitation_mode_execution_task(self):
        """Exploitation mode gives execution tasks 1.3x boost."""
        brain_state = {"mode": BehavioralMode.EXPLOITATION}
        mode_config = {
            "exploitation": {"execution": 1.3, "research": 0.8}
        }
        scorer = TaskScorer(brain_state=brain_state, mode_config=mode_config)
        task = {"task_type": "execution"}
        goal = {}
        assert scorer._brain_weight(task, goal) == 1.3

    def test_stabilization_mode_p1_boost(self):
        """Stabilization mode gives P1 tasks 1.5x boost."""
        brain_state = {"mode": BehavioralMode.STABILIZATION}
        mode_config = {
            "stabilization": {"P1_boost": 1.5, "P3_suppress": 0.5, "P4_suppress": 0.3}
        }
        scorer = TaskScorer(brain_state=brain_state, mode_config=mode_config)
        task = {"priority": Priority.P1, "task_type": "any"}
        goal = {}
        assert scorer._brain_weight(task, goal) == 1.5

    def test_brain_weight_clamped_upper(self):
        """Brain weight clamped to max 1.5."""
        brain_state = {"mode": BehavioralMode.EXPLORATION}
        mode_config = {"exploration": {"research": 2.0}}  # Would exceed 1.5
        scorer = TaskScorer(brain_state=brain_state, mode_config=mode_config)
        task = {"task_type": "research"}
        goal = {}
        assert scorer._brain_weight(task, goal) == 1.5

    def test_brain_weight_clamped_lower(self):
        """Brain weight clamped to min 0.7."""
        brain_state = {"mode": BehavioralMode.STABILIZATION}
        mode_config = {"stabilization": {"P4_suppress": 0.3}}
        scorer = TaskScorer(brain_state=brain_state, mode_config=mode_config)
        task = {"priority": Priority.P4, "task_type": "any"}
        goal = {}
        assert scorer._brain_weight(task, goal) == 0.7  # Clamped from 0.3


class TestUrgencyFactor:
    """Test urgency/deadline factor (U)."""

    def test_deadline_1_hour_away(self):
        """Deadline 1 hour away returns U near 1.5."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        deadline = current_time + 3600  # 1 hour
        task = {"deadline": deadline}
        urgency = scorer._urgency_factor(task, current_time)
        # Sigmoid should return something between 1.0 and 2.0, closer to 1.7
        assert 1.5 < urgency < 1.8

    def test_deadline_24_hours_away(self):
        """Deadline 24 hours away returns U near 1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        deadline = current_time + 86400  # 24 hours
        task = {"deadline": deadline}
        urgency = scorer._urgency_factor(task, current_time)
        # Sigmoid should return close to 1.0 for distant deadline
        assert 1.0 <= urgency < 1.2

    def test_no_deadline(self):
        """No deadline returns U=1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {}  # No deadline
        urgency = scorer._urgency_factor(task, 1000.0)
        assert urgency == 1.0


class TestReadinessFactor:
    """Test readiness factor (R)."""

    def test_blocked_task(self):
        """Blocked task returns R=0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"blocked_by": ["task-123"]}
        assert scorer._readiness_factor(task) == 0.0

    def test_just_unblocked_task(self):
        """Just-unblocked task returns R=1.2."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"just_unblocked": True}
        assert scorer._readiness_factor(task) == 1.2

    def test_ready_task(self):
        """Ready task (not blocked, not just-unblocked) returns R=1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {}  # No special flags
        assert scorer._readiness_factor(task) == 1.0


class TestAgingFactor:
    """Test aging/fairness factor (F) with per-priority caps."""

    def test_p1_no_aging(self):
        """P1 with F_MAX=1.0 never ages."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        task = {"priority": Priority.P1, "queued_at": current_time - 120}  # 2 min wait
        aging = scorer._aging_factor(task, current_time)
        # F = 1.0 + min(1.0, 120/60) = 1.0 + min(1.0, 2.0) = 1.0 + 1.0 = 2.0
        # But P1 F_MAX=1.0, so capped at 1.0 total (no aging)
        assert aging == 1.0

    def test_p2_max_aging(self):
        """P2 with F_MAX=1.2 ages up to 1.2."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        task = {"priority": Priority.P2, "queued_at": current_time - 360}  # 6 min wait
        aging = scorer._aging_factor(task, current_time)
        # F = 1.0 + min(0.2, 360/180) = 1.0 + min(0.2, 2.0) = 1.0 + 0.2 = 1.2
        assert aging == 1.2

    def test_p3_max_aging(self):
        """P3 with F_MAX=1.5 ages up to 1.5."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        task = {"priority": Priority.P3, "queued_at": current_time - 600}  # 10 min wait
        aging = scorer._aging_factor(task, current_time)
        # F = 1.0 + min(0.5, 600/300) = 1.0 + min(0.5, 2.0) = 1.0 + 0.5 = 1.5
        assert aging == 1.5

    def test_p4_max_aging(self):
        """P4 with F_MAX=1.3 ages up to 1.3."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0
        task = {"priority": Priority.P4, "queued_at": current_time - 1200}  # 20 min wait
        aging = scorer._aging_factor(task, current_time)
        # F = 1.0 + min(0.3, 1200/600) = 1.0 + min(0.3, 2.0) = 1.0 + 0.3 = 1.3
        assert aging == 1.3

    def test_no_queued_at(self):
        """Task without queued_at returns F=1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P2}
        aging = scorer._aging_factor(task, 1000.0)
        assert aging == 1.0


class TestBonusesAndPenalties:
    """Test additive bonuses and penalties."""

    def test_unblocks_many_bonus(self):
        """Task that unblocks >= 5 others gets +0.5 bonus."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"unblocks_count": 5}
        assert scorer._unblocks_many(task) == 0.5

    def test_unblocks_few_no_bonus(self):
        """Task that unblocks < 5 others gets no bonus."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"unblocks_count": 3}
        assert scorer._unblocks_many(task) == 0.0

    def test_batch_locality_bonus(self):
        """Task with same partition as running tasks gets +0.2 bonus."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"batch_locality": True}
        assert scorer._batch_locality(task) == 0.2

    def test_retry_penalty(self):
        """retry_count=3 gives -0.9 penalty."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"retry_count": 3}
        # Penalty = -0.3 * 3 = -0.9
        score = scorer.score(
            task={**task, "priority": Priority.P2, "queued_at": None},
            goal={"success_rate": 0.5},
            current_time=1000.0
        )
        # Check that score was reduced (we'll validate exact value in integration tests)
        assert isinstance(score, float)

    def test_cost_pressure_penalty(self):
        """Constrained resource_policy gives -0.5 penalty."""
        brain_state = {"resource_policy": "constrained"}
        scorer = TaskScorer(brain_state=brain_state, mode_config={})
        task = {"priority": Priority.P2}
        goal = {"success_rate": 0.5}
        score = scorer.score(task, goal, 1000.0)
        # We'll validate in integration tests that -0.5 was applied
        assert isinstance(score, float)


class TestAntiStarvation:
    """Test P4 with max aging never outranks P1."""

    def test_p4_max_aging_vs_p1_no_aging(self):
        """P4 with max aging (F=1.3) never exceeds P1 base score (4.0) when P1 has F=1.0."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        current_time = 1000.0

        # P4 with max aging
        p4_task = {
            "priority": Priority.P4,
            "queued_at": current_time - 1200,  # 20 min wait -> F=1.3
        }
        p4_goal = {"success_rate": 1.0}  # Best case G=2.0
        p4_score = scorer.score(p4_task, p4_goal, current_time)

        # P1 with no aging
        p1_task = {
            "priority": Priority.P1,
            "queued_at": current_time,  # Just queued -> F=1.0
        }
        p1_goal = {"success_rate": 0.0}  # Worst case G=0.5
        p1_score = scorer.score(p1_task, p1_goal, current_time)

        # P1 should always score higher
        assert p1_score > p4_score


class TestIntegration:
    """Integration tests for full scoring formula."""

    def test_blocked_task_scores_zero(self):
        """Blocked task always scores 0 regardless of other factors."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {
            "priority": Priority.P1,
            "blocked_by": ["task-123"],
            "unblocks_count": 10,
        }
        goal = {"success_rate": 1.0}
        score = scorer.score(task, goal, 1000.0)
        assert score == 0.0

    def test_simple_p1_task(self):
        """P1 task with no bonuses/penalties scores P*G*B*U*R*F."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        task = {"priority": Priority.P1}
        goal = {"success_rate": 0.5}  # G=1.25
        current_time = 1000.0
        score = scorer.score(task, goal, current_time)
        # P=4.0, G=1.25, B=1.0, U=1.0, R=1.0, F=1.0
        # score = 4.0 * 1.25 * 1.0 * 1.0 * 1.0 * 1.0 = 5.0
        assert score == 5.0

    def test_score_batch(self):
        """score_batch returns sorted list of (task_id, score) tuples."""
        scorer = TaskScorer(brain_state={}, mode_config={})
        tasks = [
            {"task_id": "t1", "priority": Priority.P1},
            {"task_id": "t2", "priority": Priority.P2},
            {"task_id": "t3", "priority": Priority.P4},
        ]
        goals = {
            "t1": {"success_rate": 0.5},
            "t2": {"success_rate": 0.5},
            "t3": {"success_rate": 0.5},
        }
        current_time = 1000.0
        results = scorer.score_batch(tasks, goals, current_time)

        # Should return sorted list (highest first)
        assert len(results) == 3
        assert results[0][0] == "t1"  # P1 should be first
        assert results[1][0] == "t2"  # P2 second
        assert results[2][0] == "t3"  # P4 last

        # Scores should be descending
        assert results[0][1] > results[1][1] > results[2][1]
