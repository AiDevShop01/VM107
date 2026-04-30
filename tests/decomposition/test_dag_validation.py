"""Tests for DAG validation and topological sorting."""
import pytest
from core.scheduling.dag import DAGValidator


class TestDAGValidation:
    """Test DAGValidator.validate_and_order method."""

    def test_simple_linear_dag(self):
        """A->B->C should return ['A', 'B', 'C']."""
        tasks = [
            {"task_id": "A", "dependencies": []},
            {"task_id": "B", "dependencies": ["A"]},
            {"task_id": "C", "dependencies": ["B"]},
        ]
        validator = DAGValidator()
        result = validator.validate_and_order(tasks)
        assert result == ["A", "B", "C"]

    def test_circular_dependency_raises_error(self):
        """A->B->A should raise ValueError about circular dependency."""
        tasks = [
            {"task_id": "A", "dependencies": ["B"]},
            {"task_id": "B", "dependencies": ["A"]},
        ]
        validator = DAGValidator()
        with pytest.raises(ValueError, match="Circular task dependency"):
            validator.validate_and_order(tasks)

    def test_no_dependencies_all_tasks_returned(self):
        """Tasks with no dependencies should all be returned (order irrelevant)."""
        tasks = [
            {"task_id": "A", "dependencies": []},
            {"task_id": "B", "dependencies": []},
            {"task_id": "C", "dependencies": []},
        ]
        validator = DAGValidator()
        result = validator.validate_and_order(tasks)
        assert set(result) == {"A", "B", "C"}
        assert len(result) == 3

    def test_diamond_dag(self):
        """A->B, A->C, B->D, C->D should return valid topological order."""
        tasks = [
            {"task_id": "A", "dependencies": []},
            {"task_id": "B", "dependencies": ["A"]},
            {"task_id": "C", "dependencies": ["A"]},
            {"task_id": "D", "dependencies": ["B", "C"]},
        ]
        validator = DAGValidator()
        result = validator.validate_and_order(tasks)

        # Verify topological constraints
        assert result.index("A") < result.index("B")
        assert result.index("A") < result.index("C")
        assert result.index("B") < result.index("D")
        assert result.index("C") < result.index("D")


class TestFindRunnableTasks:
    """Test DAGValidator.find_runnable_tasks method."""

    def test_returns_leaf_nodes_when_deps_completed(self):
        """When A is completed, B and C (both depend on A) should be runnable."""
        tasks = [
            {"task_id": "A", "dependencies": [], "status": "COMPLETED"},
            {"task_id": "B", "dependencies": ["A"], "status": "PENDING"},
            {"task_id": "C", "dependencies": ["A"], "status": "PENDING"},
        ]
        validator = DAGValidator()
        result = validator.find_runnable_tasks(tasks, completed_ids={"A"})
        assert set(result) == {"B", "C"}

    def test_returns_root_nodes_when_none_completed(self):
        """When nothing completed, only tasks with no dependencies are runnable."""
        tasks = [
            {"task_id": "A", "dependencies": [], "status": "PENDING"},
            {"task_id": "B", "dependencies": ["A"], "status": "PENDING"},
        ]
        validator = DAGValidator()
        result = validator.find_runnable_tasks(tasks, completed_ids=set())
        assert result == ["A"]

    def test_returns_empty_when_deps_not_met(self):
        """When B depends on A but A not completed, returns empty."""
        tasks = [
            {"task_id": "B", "dependencies": ["A"], "status": "PENDING"},
        ]
        validator = DAGValidator()
        result = validator.find_runnable_tasks(tasks, completed_ids=set())
        assert result == []

    def test_excludes_terminal_status_tasks(self):
        """Tasks with terminal status (COMPLETED, CANCELLED, FAILED) should be excluded."""
        tasks = [
            {"task_id": "A", "dependencies": [], "status": "COMPLETED"},
            {"task_id": "B", "dependencies": [], "status": "CANCELLED"},
            {"task_id": "C", "dependencies": [], "status": "FAILED"},
            {"task_id": "D", "dependencies": [], "status": "PENDING"},
        ]
        validator = DAGValidator()
        result = validator.find_runnable_tasks(tasks, completed_ids=set())
        assert result == ["D"]


class TestValidateIncrementalAdd:
    """Test DAGValidator.validate_incremental_add method."""

    def test_valid_incremental_add(self):
        """Adding D->E to existing A->B->C should return valid order."""
        existing_tasks = [
            {"task_id": "A", "dependencies": []},
            {"task_id": "B", "dependencies": ["A"]},
            {"task_id": "C", "dependencies": ["B"]},
        ]
        new_task = {"task_id": "D", "dependencies": ["C"]}

        validator = DAGValidator()
        result = validator.validate_incremental_add(existing_tasks, new_task)

        # Should return topological order including new task
        assert "D" in result
        assert result.index("C") < result.index("D")

    def test_incremental_add_detects_new_cycle(self):
        """Adding B->A to existing A->B should detect cycle."""
        existing_tasks = [
            {"task_id": "A", "dependencies": []},
            {"task_id": "B", "dependencies": ["A"]},
        ]
        new_task = {"task_id": "A", "dependencies": ["B"]}  # Creates cycle

        validator = DAGValidator()
        with pytest.raises(ValueError, match="Circular task dependency"):
            validator.validate_incremental_add(existing_tasks, new_task)
