"""
Goal decomposition engine.

Orchestrates template loading, DAG building, and validation
for goal-to-task decomposition.
"""
from typing import Any
from core.decomposition.templates import TemplateLoader, TemplateNotFoundError
from core.decomposition.dag_builder import DAGBuilder
from core.scheduling.dag import DAGValidator


class DecompositionError(Exception):
    """Raised when goal decomposition fails."""

    pass


class DecompositionEngine:
    """
    Orchestrates goal decomposition into validated task DAGs.

    Flow:
    1. Load template from TemplateLoader
    2. Build task DAG via DAGBuilder
    3. Validate DAG via DAGValidator
    4. Return TaskModel-compatible dicts
    """

    def __init__(self, template_loader: TemplateLoader, dag_validator: DAGValidator):
        """
        Initialize engine with dependencies.

        Args:
            template_loader: TemplateLoader for YAML template resolution
            dag_validator: DAGValidator for DAG cycle detection
        """
        self.loader = template_loader
        self.validator = dag_validator
        self.builder = DAGBuilder()

    def decompose(self, goal: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Decompose goal into validated task DAG.

        Args:
            goal: Goal dict with 'goal_id' and 'decomposition_template' keys

        Returns:
            List of TaskModel-compatible task dicts

        Raises:
            DecompositionError: If template not found or DAG invalid
        """
        goal_id = goal["goal_id"]
        template_id = goal["decomposition_template"]

        # Load template
        try:
            template = self.loader.load(template_id)
        except TemplateNotFoundError as e:
            raise DecompositionError(f"Template not found: {template_id}") from e

        # Build task DAG
        tasks = self.builder.build(goal_id, template)

        # Validate DAG (raises ValueError on cycle)
        try:
            self.validator.validate_and_order(tasks)
        except ValueError as e:
            raise DecompositionError(f"Invalid task DAG: {e}") from e

        return tasks

    def expand_dag(
        self,
        goal_id: str,
        template_id: str,
        parent_task_id: str,
        existing_tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Expand existing DAG with tasks from template.

        New tasks are added with dependency on parent_task_id.
        Full DAG is revalidated after expansion.

        Args:
            goal_id: Goal identifier for task ID prefix
            template_id: Template to expand from
            parent_task_id: Parent task that new tasks depend on
            existing_tasks: Current task list

        Returns:
            List of newly added tasks (not including existing tasks)

        Raises:
            DecompositionError: If template not found or expansion creates cycle
        """
        # Load expansion template
        try:
            template = self.loader.load(template_id)
        except TemplateNotFoundError as e:
            raise DecompositionError(f"Template not found: {template_id}") from e

        # Build new tasks from template
        new_tasks = self.builder.build(goal_id, template)

        # Inject parent dependency into first task
        if new_tasks:
            # Add parent to dependencies of first new task
            first_task_deps = new_tasks[0].get("dependencies", [])
            if parent_task_id not in first_task_deps:
                new_tasks[0]["dependencies"] = [parent_task_id] + first_task_deps

        # Merge into existing DAG
        merged_tasks = existing_tasks + new_tasks

        # Revalidate full DAG
        try:
            self.validator.validate_and_order(merged_tasks)
        except ValueError as e:
            raise DecompositionError(f"DAG expansion creates cycle: {e}") from e

        return new_tasks
