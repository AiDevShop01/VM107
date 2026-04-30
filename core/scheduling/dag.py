"""
DAG validation and topological sorting for task dependency graphs.

Uses Python's stdlib graphlib.TopologicalSorter for cycle detection
and topological ordering of task dependencies.
"""
from graphlib import TopologicalSorter, CycleError
from typing import Any


class DAGValidator:
    """
    Validates task dependency DAGs and provides task ordering.

    Uses graphlib.TopologicalSorter for:
    - Cycle detection (raises ValueError on circular dependencies)
    - Topological ordering (returns valid execution order)
    - Incremental validation (validates new tasks added at runtime)
    """

    TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "FAILED"}

    def validate_and_order(self, tasks: list[dict[str, Any]]) -> list[str]:
        """
        Validate DAG structure and return topologically sorted task IDs.

        Args:
            tasks: List of task dicts, each with 'task_id' and 'dependencies' keys

        Returns:
            List of task_ids in valid topological execution order

        Raises:
            ValueError: If circular dependency detected
        """
        # Build dependency graph
        graph: dict[str, list[str]] = {}
        for task in tasks:
            task_id = task["task_id"]
            dependencies = task.get("dependencies", [])
            graph[task_id] = dependencies

        # Use TopologicalSorter for validation and ordering
        sorter = TopologicalSorter(graph)

        try:
            # static_order() calls prepare() internally
            return list(sorter.static_order())
        except CycleError as e:
            raise ValueError(f"Circular task dependency detected: {e}")

    def find_runnable_tasks(
        self, tasks: list[dict[str, Any]], completed_ids: set[str]
    ) -> list[str]:
        """
        Find tasks that are ready to run (all dependencies completed).

        Args:
            tasks: List of task dicts with 'task_id', 'dependencies', and 'status'
            completed_ids: Set of task_ids that have been completed

        Returns:
            List of task_ids that can be executed (dependencies met, not terminal)
        """
        runnable = []

        for task in tasks:
            task_id = task["task_id"]
            status = task.get("status", "PENDING")
            dependencies = set(task.get("dependencies", []))

            # Skip if task is in terminal state
            if status in self.TERMINAL_STATUSES:
                continue

            # Task is runnable if all dependencies are completed
            if dependencies.issubset(completed_ids):
                runnable.append(task_id)

        return runnable

    def validate_incremental_add(
        self, existing_tasks: list[dict[str, Any]], new_task: dict[str, Any]
    ) -> list[str]:
        """
        Validate adding a new task to existing DAG.

        Args:
            existing_tasks: Current task list
            new_task: New task to add (may update existing task)

        Returns:
            Updated topological order including new task

        Raises:
            ValueError: If new task creates a circular dependency
        """
        # Merge existing and new task (replacing if task_id matches)
        task_map = {task["task_id"]: task for task in existing_tasks}
        task_map[new_task["task_id"]] = new_task
        merged_tasks = list(task_map.values())

        # Revalidate full DAG
        return self.validate_and_order(merged_tasks)
