"""
Tests for PreemptionManager - cooperative pre-emption with 5-condition check.

Tests all 5 conditions (P1, deadline risk, no free worker, preemptible task, gain > cost),
max pre-emptions per cycle, cooldown window, and target selection logic.
"""

import pytest
from core.scheduling.preemption import PreemptionManager, PreemptionResult
from core.scheduling.enums import Priority


class TestAllConditionsTrue:
    """Test pre-emption when all 5 conditions are met."""

    def test_all_conditions_true(self):
        """All 5 conditions true: returns should_preempt=True with target."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-urgent",
            "priority": Priority.P1,
            "deadline": 1000.0,  # Deadline risk
            "estimated_gain": 100.0,
        }
        running_tasks = [
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "estimated_cost": 50.0,
            }
        ]
        available_workers = 0  # No free workers
        threshold = 1.5  # gain/cost threshold

        result = manager.check_preemption(
            incoming_task, running_tasks, available_workers, threshold
        )

        assert result.should_preempt is True
        assert result.target_task_id == "p2-running"
        assert "approved" in result.reason.lower()


class TestCondition1IncomingNotP1:
    """Test Condition 1: Incoming task must be P1."""

    def test_incoming_p2_no_preemption(self):
        """Incoming P2 task: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p2-task",
            "priority": Priority.P2,
            "deadline": 1000.0,
            "estimated_gain": 100.0,
        }
        running_tasks = [
            {
                "task_id": "p3-running",
                "priority": Priority.P3,
                "preemptible": True,
                "estimated_cost": 10.0,
            }
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False
        assert "not P1" in result.reason or "priority" in result.reason.lower()

    def test_incoming_p4_no_preemption(self):
        """Incoming P4 task: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p4-task",
            "priority": Priority.P4,
            "deadline": 1000.0,
        }
        running_tasks = [
            {"task_id": "p3-running", "priority": Priority.P3, "preemptible": True}
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False


class TestCondition2DeadlineRisk:
    """Test Condition 2: SLA/deadline breach risk."""

    def test_no_deadline_no_preemption(self):
        """No deadline: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-no-deadline",
            "priority": Priority.P1,
            # No deadline field
        }
        running_tasks = [
            {"task_id": "p2-running", "priority": Priority.P2, "preemptible": True}
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False
        assert "deadline" in result.reason.lower()


class TestCondition3FreeWorker:
    """Test Condition 3: No free worker available."""

    def test_free_worker_available_no_preemption(self):
        """Free worker available: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
        }
        running_tasks = [
            {"task_id": "p2-running", "priority": Priority.P2, "preemptible": True}
        ]
        available_workers = 1  # Free worker

        result = manager.check_preemption(incoming_task, running_tasks, available_workers, 1.5)

        assert result.should_preempt is False
        assert "free worker" in result.reason.lower() or "worker available" in result.reason.lower()


class TestCondition4PreemptibleTask:
    """Test Condition 4: Running task declared preemptible=True."""

    def test_no_preemptible_tasks_no_preemption(self):
        """No preemptible running tasks: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
        }
        running_tasks = [
            {"task_id": "p2-running", "priority": Priority.P2, "preemptible": False},
            {"task_id": "p3-running", "priority": Priority.P3, "preemptible": False},
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False
        assert "preemptible" in result.reason.lower()

    def test_missing_preemptible_field_defaults_false(self):
        """Missing preemptible field defaults to False: no pre-emption."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
        }
        running_tasks = [
            {"task_id": "p2-running", "priority": Priority.P2}  # No preemptible field
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False


class TestCondition5GainVsCost:
    """Test Condition 5: Expected gain > cost * threshold."""

    def test_gain_below_threshold_no_preemption(self):
        """Gain below cost * threshold: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
            "estimated_gain": 100.0,
        }
        running_tasks = [
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "estimated_cost": 100.0,  # gain/cost = 100/100 = 1.0 < 1.5
            }
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False
        assert "gain" in result.reason.lower() or "cost" in result.reason.lower()

    def test_missing_gain_or_cost_no_preemption(self):
        """Missing gain or cost fields: returns should_preempt=False."""
        manager = PreemptionManager()
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
            # No estimated_gain
        }
        running_tasks = [
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "estimated_cost": 50.0,
            }
        ]

        result = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)

        assert result.should_preempt is False


class TestMaxPreemptionsPerCycle:
    """Test max pre-emptions per cycle cap."""

    def test_max_preemptions_reached(self):
        """After max pre-emptions, returns should_preempt=False."""
        manager = PreemptionManager(max_preemptions_per_cycle=2)
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
            "estimated_gain": 100.0,
        }
        running_tasks = [
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "estimated_cost": 50.0,
            }
        ]

        # First two pre-emptions should succeed
        result1 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result1.should_preempt is True

        result2 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result2.should_preempt is True

        # Third pre-emption should fail (max reached)
        result3 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result3.should_preempt is False
        assert "max" in result3.reason.lower() or "limit" in result3.reason.lower()

    def test_reset_cycle_clears_counter(self):
        """reset_cycle() clears preemptions_this_cycle counter."""
        manager = PreemptionManager(max_preemptions_per_cycle=1)
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
            "estimated_gain": 100.0,
        }
        running_tasks = [
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "estimated_cost": 50.0,
            }
        ]

        # First pre-emption succeeds
        result1 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result1.should_preempt is True

        # Second fails (max reached)
        result2 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result2.should_preempt is False

        # Reset cycle
        manager.reset_cycle()

        # Now succeeds again
        result3 = manager.check_preemption(incoming_task, running_tasks, 0, 1.5)
        assert result3.should_preempt is True


class TestCooldown:
    """Test cooldown window prevents re-preemption."""

    def test_task_in_cooldown_not_preemptible(self):
        """Task pre-empted recently not eligible within cooldown window."""
        manager = PreemptionManager(cooldown_seconds=60)
        incoming_task = {
            "task_id": "p1-task",
            "priority": Priority.P1,
            "deadline": 1000.0,
            "estimated_gain": 100.0,
        }

        # Task just pre-empted
        running_task = {
            "task_id": "p2-running",
            "priority": Priority.P2,
            "preemptible": True,
            "estimated_cost": 50.0,
        }

        # First pre-emption
        result1 = manager.check_preemption(incoming_task, [running_task], 0, 1.5)
        assert result1.should_preempt is True
        assert result1.target_task_id == "p2-running"

        # Record pre-emption timestamp (simulating actual pre-emption)
        manager._record_preemption("p2-running", 1000.0)

        # Try to pre-empt same task again immediately (still in cooldown)
        result2 = manager.check_preemption(incoming_task, [running_task], 0, 1.5)
        # Should not select same task (but may select others if available)
        # If only task is in cooldown, should_preempt=False
        if result2.should_preempt:
            assert result2.target_task_id != "p2-running"

    def test_cooldown_expired_allows_preemption(self):
        """Task eligible again after cooldown window expires."""
        manager = PreemptionManager(cooldown_seconds=60)

        # Record pre-emption at time 1000
        manager._record_preemption("p2-running", 1000.0)

        # Check eligibility at time 1000 (just pre-empted)
        assert not manager._is_eligible_for_preemption("p2-running", 1000.0)

        # Check eligibility at time 1030 (still in cooldown)
        assert not manager._is_eligible_for_preemption("p2-running", 1030.0)

        # Check eligibility at time 1061 (cooldown expired)
        assert manager._is_eligible_for_preemption("p2-running", 1061.0)


class TestTargetSelection:
    """Test select_preemption_target logic."""

    def test_selects_lowest_priority_preemptible(self):
        """Among preemptible tasks, selects lowest priority (highest P number)."""
        manager = PreemptionManager()
        running_tasks = [
            {
                "task_id": "p1-running",
                "priority": Priority.P1,
                "preemptible": True,
                "started_at": 1000.0,
            },
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "started_at": 1000.0,
            },
            {
                "task_id": "p3-running",
                "priority": Priority.P3,
                "preemptible": True,
                "started_at": 1000.0,
            },
        ]

        target = manager.select_preemption_target(running_tasks, 1000.0)
        assert target == "p3-running"  # Lowest priority (P3)

    def test_tie_break_by_longest_running(self):
        """Tie-break by longest running time when priorities equal."""
        manager = PreemptionManager()
        running_tasks = [
            {
                "task_id": "p2-newer",
                "priority": Priority.P2,
                "preemptible": True,
                "started_at": 1100.0,
            },
            {
                "task_id": "p2-older",
                "priority": Priority.P2,
                "preemptible": True,
                "started_at": 1000.0,
            },
        ]

        target = manager.select_preemption_target(running_tasks, 1200.0)
        assert target == "p2-older"  # Longest running

    def test_skips_non_preemptible(self):
        """Skips non-preemptible tasks."""
        manager = PreemptionManager()
        running_tasks = [
            {
                "task_id": "p3-not-preemptible",
                "priority": Priority.P3,
                "preemptible": False,
                "started_at": 1000.0,
            },
            {
                "task_id": "p2-preemptible",
                "priority": Priority.P2,
                "preemptible": True,
                "started_at": 1000.0,
            },
        ]

        target = manager.select_preemption_target(running_tasks, 1000.0)
        assert target == "p2-preemptible"

    def test_skips_cooldown_tasks(self):
        """Skips tasks in cooldown window."""
        manager = PreemptionManager(cooldown_seconds=60)

        # Record pre-emption of p3-running
        manager._record_preemption("p3-running", 1000.0)

        running_tasks = [
            {
                "task_id": "p3-running",
                "priority": Priority.P3,
                "preemptible": True,
                "started_at": 1000.0,
            },
            {
                "task_id": "p2-running",
                "priority": Priority.P2,
                "preemptible": True,
                "started_at": 1000.0,
            },
        ]

        # At time 1030 (still in cooldown), should skip p3-running
        target = manager.select_preemption_target(running_tasks, 1030.0)
        assert target == "p2-running"

    def test_no_eligible_targets_returns_none(self):
        """No eligible targets returns None."""
        manager = PreemptionManager()
        running_tasks = [
            {
                "task_id": "p2-not-preemptible",
                "priority": Priority.P2,
                "preemptible": False,
            }
        ]

        target = manager.select_preemption_target(running_tasks, 1000.0)
        assert target is None


class TestPreemptionResult:
    """Test PreemptionResult dataclass."""

    def test_result_structure(self):
        """PreemptionResult has expected fields."""
        result = PreemptionResult(
            should_preempt=True,
            target_task_id="task-123",
            reason="All conditions met"
        )
        assert result.should_preempt is True
        assert result.target_task_id == "task-123"
        assert result.reason == "All conditions met"

    def test_result_none_target(self):
        """PreemptionResult can have None target_task_id."""
        result = PreemptionResult(
            should_preempt=False,
            target_task_id=None,
            reason="Condition 1 failed"
        )
        assert result.should_preempt is False
        assert result.target_task_id is None
