"""
DAG builder for converting templates to task DAGs.

Resolves task IDs and dependencies from template suffixes
to full goal-scoped task identifiers.
"""
from typing import Any
from core.decomposition.templates import TaskTemplate


class DAGBuilder:
    """
    Builds task DAG from template by resolving IDs and dependencies.

    Task IDs are generated as: {goal_id}:{task_id_suffix}
    Dependencies are resolved from suffixes to full IDs.
    """

    def build(self, goal_id: str, template: TaskTemplate) -> list[dict[str, Any]]:
        """
        Build task DAG from template.

        Args:
            goal_id: Goal identifier for task ID prefix
            template: TaskTemplate to instantiate

        Returns:
            List of task dicts with resolved IDs and dependencies
        """
        tasks = []

        for task_entry in template.tasks:
            # Generate full task ID
            task_id = f"{goal_id}:{task_entry.task_id_suffix}"

            # Resolve dependency suffixes to full task IDs
            dependencies = [
                f"{goal_id}:{dep_suffix}" for dep_suffix in task_entry.dependencies
            ]

            # Build task dict
            task_dict = {
                "task_id": task_id,
                "task_type": task_entry.task_type,
                "priority": task_entry.priority,
                "dependencies": dependencies,
                "estimated_cost_usd": task_entry.estimated_cost_usd,
                "parameters": task_entry.parameters,
            }

            tasks.append(task_dict)

        return tasks
