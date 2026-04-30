"""Tests for decomposition engine, template loader, and DAG builder."""
import pytest
from pathlib import Path
from core.decomposition.templates import (
    TemplateLoader,
    TaskTemplate,
    TemplateNotFoundError,
)
from core.decomposition.dag_builder import DAGBuilder
from core.decomposition.engine import DecompositionEngine, DecompositionError
from core.scheduling.dag import DAGValidator


@pytest.fixture
def templates_dir(tmp_path):
    """Create a temporary templates directory with sample YAML files."""
    templates = tmp_path / "templates"
    templates.mkdir()

    # Valid research template
    research_yaml = templates / "research_v1.yaml"
    research_yaml.write_text("""
template_id: research_v1
goal_type: research
version: 1
tasks:
  - task_id_suffix: data_collection
    task_type: data_fetch
    priority: P2
    dependencies: []
    estimated_cost_usd: 0.5
  - task_id_suffix: analysis
    task_type: analysis
    priority: P2
    dependencies: [data_collection]
    estimated_cost_usd: 1.0
  - task_id_suffix: synthesis
    task_type: synthesis
    priority: P3
    dependencies: [analysis]
    estimated_cost_usd: 0.5
""")

    # Template with circular dependency (should fail validation)
    circular_yaml = templates / "circular_v1.yaml"
    circular_yaml.write_text("""
template_id: circular_v1
goal_type: test
version: 1
tasks:
  - task_id_suffix: task_a
    task_type: test
    priority: P2
    dependencies: [task_b]
    estimated_cost_usd: 0.1
  - task_id_suffix: task_b
    task_type: test
    priority: P2
    dependencies: [task_a]
    estimated_cost_usd: 0.1
""")

    # Template with invalid dependency reference
    invalid_dep_yaml = templates / "invalid_dep_v1.yaml"
    invalid_dep_yaml.write_text("""
template_id: invalid_dep_v1
goal_type: test
version: 1
tasks:
  - task_id_suffix: task_a
    task_type: test
    priority: P2
    dependencies: [nonexistent_task]
    estimated_cost_usd: 0.1
""")

    # Template with duplicate task_id_suffix
    duplicate_yaml = templates / "duplicate_v1.yaml"
    duplicate_yaml.write_text("""
template_id: duplicate_v1
goal_type: test
version: 1
tasks:
  - task_id_suffix: task_a
    task_type: test
    priority: P2
    dependencies: []
    estimated_cost_usd: 0.1
  - task_id_suffix: task_a
    task_type: test
    priority: P2
    dependencies: []
    estimated_cost_usd: 0.1
""")

    return templates


class TestTemplateLoader:
    """Test TemplateLoader YAML loading and validation."""

    def test_load_valid_template(self, templates_dir):
        """Loading valid template should return TaskTemplate with correct structure."""
        loader = TemplateLoader(templates_dir)
        template = loader.load("research_v1")

        assert template.template_id == "research_v1"
        assert template.goal_type == "research"
        assert template.version == 1
        assert len(template.tasks) == 3
        assert template.tasks[0].task_id_suffix == "data_collection"
        assert template.tasks[1].task_id_suffix == "analysis"
        assert template.tasks[2].task_id_suffix == "synthesis"

    def test_load_nonexistent_template_raises_error(self, templates_dir):
        """Loading nonexistent template should raise TemplateNotFoundError."""
        loader = TemplateLoader(templates_dir)
        with pytest.raises(TemplateNotFoundError, match="nonexistent"):
            loader.load("nonexistent")

    def test_template_validates_suffix_uniqueness(self, templates_dir):
        """Template with duplicate task_id_suffix should fail validation."""
        loader = TemplateLoader(templates_dir)
        with pytest.raises(ValueError, match="Duplicate task_id_suffix"):
            loader.load("duplicate_v1")

    def test_template_validates_dependency_references(self, templates_dir):
        """Template with invalid dependency reference should fail validation."""
        loader = TemplateLoader(templates_dir)
        with pytest.raises(ValueError, match="Invalid dependency reference"):
            loader.load("invalid_dep_v1")


class TestDAGBuilder:
    """Test DAGBuilder task ID resolution."""

    def test_build_generates_resolved_task_ids(self, templates_dir):
        """DAGBuilder should generate task IDs as {goal_id}:{suffix}."""
        loader = TemplateLoader(templates_dir)
        template = loader.load("research_v1")
        builder = DAGBuilder()

        tasks = builder.build(goal_id="goal-123", template=template)

        assert len(tasks) == 3
        assert tasks[0]["task_id"] == "goal-123:data_collection"
        assert tasks[1]["task_id"] == "goal-123:analysis"
        assert tasks[2]["task_id"] == "goal-123:synthesis"

    def test_build_maps_template_dependencies_to_full_ids(self, templates_dir):
        """DAGBuilder should resolve dependency suffixes to full task IDs."""
        loader = TemplateLoader(templates_dir)
        template = loader.load("research_v1")
        builder = DAGBuilder()

        tasks = builder.build(goal_id="goal-123", template=template)

        # data_collection has no dependencies
        assert tasks[0]["dependencies"] == []

        # analysis depends on data_collection
        assert tasks[1]["dependencies"] == ["goal-123:data_collection"]

        # synthesis depends on analysis
        assert tasks[2]["dependencies"] == ["goal-123:analysis"]


class TestDecompositionEngine:
    """Test DecompositionEngine end-to-end orchestration."""

    def test_decompose_returns_task_dicts(self, templates_dir):
        """decompose() should return list of TaskModel-compatible dicts."""
        loader = TemplateLoader(templates_dir)
        validator = DAGValidator()
        engine = DecompositionEngine(loader, validator)

        goal = {
            "goal_id": "goal-456",
            "decomposition_template": "research_v1",
        }

        tasks = engine.decompose(goal)

        assert len(tasks) == 3
        assert all("task_id" in task for task in tasks)
        assert all("dependencies" in task for task in tasks)
        assert all("task_type" in task for task in tasks)

    def test_decompose_validates_dag(self, templates_dir):
        """decompose() should raise DecompositionError for invalid DAG."""
        loader = TemplateLoader(templates_dir)
        validator = DAGValidator()
        engine = DecompositionEngine(loader, validator)

        goal = {
            "goal_id": "goal-789",
            "decomposition_template": "circular_v1",
        }

        with pytest.raises(DecompositionError, match="Circular"):
            engine.decompose(goal)

    def test_expand_dag_adds_tasks_with_parent_dependency(self, templates_dir):
        """expand_dag() should add new tasks with dependency on parent."""
        loader = TemplateLoader(templates_dir)
        validator = DAGValidator()
        engine = DecompositionEngine(loader, validator)

        # Initial goal decomposition
        goal = {
            "goal_id": "goal-999",
            "decomposition_template": "research_v1",
        }
        existing_tasks = engine.decompose(goal)

        # Expand with new template
        new_tasks = engine.expand_dag(
            goal_id="goal-999",
            template_id="research_v1",
            parent_task_id="goal-999:synthesis",
            existing_tasks=existing_tasks,
        )

        # New tasks should have IDs prefixed with goal_id
        assert all("goal-999:" in task["task_id"] for task in new_tasks)

        # First new task should depend on parent
        assert "goal-999:synthesis" in new_tasks[0]["dependencies"]

    def test_expand_dag_rejects_unregistered_template(self, templates_dir):
        """expand_dag() should raise DecompositionError for unregistered template."""
        loader = TemplateLoader(templates_dir)
        validator = DAGValidator()
        engine = DecompositionEngine(loader, validator)

        with pytest.raises(DecompositionError, match="Template not found"):
            engine.expand_dag(
                goal_id="goal-999",
                template_id="nonexistent",
                parent_task_id="task-1",
                existing_tasks=[],
            )

    def test_expand_dag_revalidates_full_dag(self, templates_dir):
        """expand_dag() should revalidate full DAG after expansion."""
        loader = TemplateLoader(templates_dir)
        validator = DAGValidator()
        engine = DecompositionEngine(loader, validator)

        # Create existing tasks with potential cycle risk
        existing_tasks = [
            {"task_id": "goal-888:task_a", "dependencies": []},
        ]

        # Try to expand with circular template (should fail validation)
        with pytest.raises(DecompositionError, match="Circular"):
            engine.expand_dag(
                goal_id="goal-888",
                template_id="circular_v1",
                parent_task_id="goal-888:task_a",
                existing_tasks=existing_tasks,
            )
