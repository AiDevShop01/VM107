"""
YAML template loader and validator for goal decomposition.

Templates define task DAG structures that can be instantiated
for specific goals.
"""
from pathlib import Path
from typing import Any
from pydantic import BaseModel, field_validator, ConfigDict
import yaml


class TemplateNotFoundError(Exception):
    """Raised when template file not found."""

    pass


class TaskTemplateEntry(BaseModel):
    """Single task entry within a template."""

    model_config = ConfigDict(extra="forbid")

    task_id_suffix: str
    task_type: str
    priority: str
    dependencies: list[str] = []
    estimated_cost_usd: float
    parameters: dict[str, Any] = {}


class TaskTemplate(BaseModel):
    """
    Task template loaded from YAML.

    Validates:
    - task_id_suffix uniqueness within template
    - All dependency references exist within template
    """

    model_config = ConfigDict(extra="forbid")

    template_id: str
    goal_type: str
    version: int
    tasks: list[TaskTemplateEntry]

    @field_validator("tasks")
    @classmethod
    def validate_task_uniqueness(cls, tasks: list[TaskTemplateEntry]) -> list[TaskTemplateEntry]:
        """Validate task_id_suffix uniqueness within template."""
        suffixes = [task.task_id_suffix for task in tasks]
        duplicates = [suffix for suffix in suffixes if suffixes.count(suffix) > 1]

        if duplicates:
            unique_duplicates = sorted(set(duplicates))
            raise ValueError(
                f"Duplicate task_id_suffix found: {', '.join(unique_duplicates)}"
            )

        return tasks

    @field_validator("tasks")
    @classmethod
    def validate_dependency_references(cls, tasks: list[TaskTemplateEntry]) -> list[TaskTemplateEntry]:
        """Validate all dependency references exist within template."""
        valid_suffixes = {task.task_id_suffix for task in tasks}

        for task in tasks:
            for dep in task.dependencies:
                if dep not in valid_suffixes:
                    raise ValueError(
                        f"Invalid dependency reference '{dep}' in task '{task.task_id_suffix}'. "
                        f"Valid references: {sorted(valid_suffixes)}"
                    )

        return tasks


class TemplateLoader:
    """
    Loads and validates YAML templates from a directory.

    Templates are YAML files following the naming convention:
    {template_id}.yaml
    """

    def __init__(self, templates_dir: Path | str):
        """
        Initialize loader with templates directory.

        Args:
            templates_dir: Path to directory containing YAML templates
        """
        self.templates_dir = Path(templates_dir)

    def load(self, template_id: str) -> TaskTemplate:
        """
        Load and validate template by ID.

        Args:
            template_id: Template identifier (filename without .yaml extension)

        Returns:
            Validated TaskTemplate instance

        Raises:
            TemplateNotFoundError: If template file not found
            ValueError: If template validation fails
        """
        template_path = self.templates_dir / f"{template_id}.yaml"

        if not template_path.exists():
            raise TemplateNotFoundError(
                f"Template not found: {template_id} (expected path: {template_path})"
            )

        with template_path.open("r") as f:
            data = yaml.safe_load(f)

        # Pydantic validation (including custom validators)
        return TaskTemplate(**data)
