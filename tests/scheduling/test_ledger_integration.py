"""
Integration tests for MongoTaskLedger and MongoProgressLedger.

Tests verify Protocol satisfaction, MongoDB integration, and graceful degradation.
"""
import pytest
from pathlib import Path
from datetime import datetime, timezone
from core.interfaces.task_ledger import (
    TaskLedgerInterface,
    NoOpTaskLedger,
    MongoTaskLedger
)
from core.interfaces.progress_ledger import (
    ProgressLedgerInterface,
    NoOpProgressLedger,
    MongoProgressLedger
)
from core.execution_context import ExecutionContext, StepResult
from core.boundary.config_resolver import BoundaryConfig, ConfigResolver


class TestTaskLedgerProtocol:
    """Test TaskLedgerInterface Protocol satisfaction."""

    @pytest.mark.asyncio
    async def test_noop_satisfies_protocol(self):
        """Verify NoOpTaskLedger satisfies TaskLedgerInterface Protocol."""
        ledger = NoOpTaskLedger()
        assert isinstance(ledger, TaskLedgerInterface)

    @pytest.mark.asyncio
    async def test_mongo_satisfies_protocol_with_valid_uri(self):
        """Verify MongoTaskLedger satisfies Protocol with valid URI."""
        # Use localhost MongoDB (assumes dev MongoDB available)
        ledger = MongoTaskLedger("mongodb://192.168.1.151:27017/", "fingpt_agents")
        assert isinstance(ledger, TaskLedgerInterface)

    @pytest.mark.asyncio
    async def test_mongo_satisfies_protocol_with_invalid_uri(self):
        """Verify MongoTaskLedger satisfies Protocol even with invalid URI (graceful degradation)."""
        ledger = MongoTaskLedger("mongodb://invalid-host:27017/", "fingpt_agents")
        assert isinstance(ledger, TaskLedgerInterface)


class TestProgressLedgerProtocol:
    """Test ProgressLedgerInterface Protocol satisfaction."""

    @pytest.mark.asyncio
    async def test_noop_satisfies_protocol(self):
        """Verify NoOpProgressLedger satisfies ProgressLedgerInterface Protocol."""
        ledger = NoOpProgressLedger()
        assert isinstance(ledger, ProgressLedgerInterface)

    @pytest.mark.asyncio
    async def test_mongo_satisfies_protocol_with_valid_uri(self):
        """Verify MongoProgressLedger satisfies Protocol with valid URI."""
        ledger = MongoProgressLedger("mongodb://192.168.1.151:27017/", "fingpt_agents")
        assert isinstance(ledger, ProgressLedgerInterface)

    @pytest.mark.asyncio
    async def test_mongo_satisfies_protocol_with_invalid_uri(self):
        """Verify MongoProgressLedger satisfies Protocol even with invalid URI (graceful degradation)."""
        ledger = MongoProgressLedger("mongodb://invalid-host:27017/", "fingpt_agents")
        assert isinstance(ledger, ProgressLedgerInterface)


class TestMongoTaskLedgerFunctionality:
    """Test MongoTaskLedger functionality with real MongoDB."""

    @pytest.fixture
    def mongo_uri(self):
        """MongoDB URI for dev environment."""
        return "mongodb://192.168.1.151:27017/"

    @pytest.fixture
    def test_database(self):
        """Test database name."""
        return "test_fingpt_agents"

    @pytest.fixture
    def ledger(self, mongo_uri, test_database):
        """Create MongoTaskLedger instance."""
        ledger = MongoTaskLedger(mongo_uri, test_database)
        yield ledger
        # Cleanup: Drop test database after tests
        if ledger._mongodb_available:
            ledger._client.drop_database(test_database)

    @pytest.fixture
    def sample_task(self, ledger):
        """Insert sample task for testing."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        task_id = "test-task-001"
        goal_id = "test-goal-001"

        # Insert goal
        ledger._goals.insert_one({
            "_id": goal_id,
            "name": "Test Goal",
            "budget_max_cost_usd": 10.0,
            "budget_max_tokens": 100000,
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc)
        })

        # Insert task
        ledger._tasks.insert_one({
            "_id": task_id,
            "goal_id": goal_id,
            "name": "Test Task",
            "status": "PENDING",
            "blocked_by": ["dep-task-001"],
            "version": 0,
            "created_at": datetime.now(timezone.utc)
        })

        # Insert dependency task
        ledger._tasks.insert_one({
            "_id": "dep-task-001",
            "name": "Dependency Task",
            "status": "COMPLETED",
            "version": 0,
            "created_at": datetime.now(timezone.utc)
        })

        return task_id

    @pytest.mark.asyncio
    async def test_get_plan_returns_enriched_dict(self, ledger, sample_task):
        """Test get_plan returns enriched dict with goal context."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        plan = await ledger.get_plan(sample_task)

        # Verify structure
        assert "task" in plan
        assert "goal" in plan
        assert "dependencies" in plan

        # Verify task data
        assert plan["task"]["_id"] == sample_task
        assert plan["task"]["name"] == "Test Task"

        # Verify goal data
        assert plan["goal"]["_id"] == "test-goal-001"
        assert plan["goal"]["budget_max_cost_usd"] == 10.0
        assert plan["goal"]["budget_max_tokens"] == 100000

        # Verify dependencies
        assert len(plan["dependencies"]) == 1
        assert plan["dependencies"][0]["task_id"] == "dep-task-001"
        assert plan["dependencies"][0]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_update_applies_optimistic_concurrency(self, ledger, sample_task):
        """Test update applies optimistic concurrency with version check."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        # First update should succeed
        await ledger.update(sample_task, {"status": "IN_PROGRESS"})

        # Verify update
        task_doc = ledger._tasks.find_one({"_id": sample_task})
        assert task_doc["status"] == "IN_PROGRESS"
        assert task_doc["version"] == 1

        # Second update should succeed with new version
        await ledger.update(sample_task, {"status": "COMPLETED"})

        # Verify update
        task_doc = ledger._tasks.find_one({"_id": sample_task})
        assert task_doc["status"] == "COMPLETED"
        assert task_doc["version"] == 2

    @pytest.mark.asyncio
    async def test_graceful_mongodb_unavailable_fallback(self):
        """Test graceful fallback when MongoDB unavailable."""
        ledger = MongoTaskLedger("mongodb://invalid-host:27017/", "fingpt_agents")

        # Should return empty dict (NoOp behavior)
        plan = await ledger.get_plan("any-task-id")
        assert plan == {}

        # Should not raise exception
        await ledger.update("any-task-id", {"status": "COMPLETED"})


class TestMongoProgressLedgerFunctionality:
    """Test MongoProgressLedger functionality with real MongoDB."""

    @pytest.fixture
    def mongo_uri(self):
        """MongoDB URI for dev environment."""
        return "mongodb://192.168.1.151:27017/"

    @pytest.fixture
    def test_database(self):
        """Test database name."""
        return "test_fingpt_agents"

    @pytest.fixture
    def ledger(self, mongo_uri, test_database):
        """Create MongoProgressLedger instance."""
        ledger = MongoProgressLedger(mongo_uri, test_database)
        yield ledger
        # Cleanup: Drop test database after tests
        if ledger._mongodb_available:
            ledger._client.drop_database(test_database)

    @pytest.mark.asyncio
    async def test_record_step_buffers_writes(self, ledger):
        """Test record_step buffers writes for batching."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        # Record multiple steps
        for i in range(5):
            result = StepResult(
                step_id=f"task-001:{i}",
                outcome="success",
                metadata={
                    "token_count_delta": 100,
                    "cost_usd_delta": 0.01
                }
            )
            await ledger.record_step(result)

        # Buffer should have 5 entries
        assert len(ledger._buffer) == 5

        # Force flush
        ledger.flush_all()

        # Buffer should be empty
        assert len(ledger._buffer) == 0

        # Verify MongoDB has progress document
        progress_doc = ledger._progress.find_one({"_id": "task-001"})
        assert progress_doc is not None
        assert progress_doc["step_count"] == 5
        assert progress_doc["total_tokens"] == 500
        assert progress_doc["total_cost_usd"] == 0.05

    @pytest.mark.asyncio
    async def test_get_next_action_returns_none_for_new_task(self, ledger):
        """Test get_next_action returns None for new task with no progress."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        context = ExecutionContext(task_id="new-task-001")
        next_action = await ledger.get_next_action(context)

        assert next_action is None

    @pytest.mark.asyncio
    async def test_graceful_mongodb_unavailable_fallback(self):
        """Test graceful fallback when MongoDB unavailable."""
        ledger = MongoProgressLedger("mongodb://invalid-host:27017/", "fingpt_agents")

        # Should return None (NoOp behavior)
        context = ExecutionContext(task_id="any-task-id")
        next_action = await ledger.get_next_action(context)
        assert next_action is None

        # Should not raise exception
        result = StepResult(
            step_id="any-step-id",
            outcome="success",
            metadata={}
        )
        await ledger.record_step(result)


class TestConfigResolverIntegration:
    """Test ConfigResolver Level 2 integration with task/goal constraints."""

    @pytest.fixture
    def boundary_yaml_path(self):
        """Path to boundary.yaml."""
        vm107_root = Path(__file__).parent.parent.parent
        return str(vm107_root / "config" / "boundary.yaml")

    @pytest.fixture
    def mongo_uri(self):
        """MongoDB URI for dev environment."""
        return "mongodb://192.168.1.151:27017/"

    @pytest.fixture
    def test_database(self):
        """Test database name."""
        return "test_fingpt_agents"

    @pytest.fixture
    def ledger(self, mongo_uri, test_database):
        """Create MongoTaskLedger instance."""
        ledger = MongoTaskLedger(mongo_uri, test_database)
        yield ledger
        # Cleanup: Drop test database after tests
        if ledger._mongodb_available:
            ledger._client.drop_database(test_database)

    @pytest.mark.asyncio
    async def test_goal_budget_constraints_via_config_resolver(
        self, ledger, boundary_yaml_path
    ):
        """Test goal budget limits flow through ConfigResolver Level 2."""
        if not ledger._mongodb_available:
            pytest.skip("MongoDB not available")

        # Setup: Create goal with budget constraints
        goal_id = "test-goal-budget"
        task_id = "test-task-budget"

        ledger._goals.insert_one({
            "_id": goal_id,
            "name": "Budget-Limited Goal",
            "budget_max_cost_usd": 5.0,
            "budget_max_tokens": 100000,
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc)
        })

        ledger._tasks.insert_one({
            "_id": task_id,
            "goal_id": goal_id,
            "name": "Budget-Limited Task",
            "status": "PENDING",
            "version": 0,
            "created_at": datetime.now(timezone.utc)
        })

        # Fetch task plan with goal metadata
        plan = await ledger.get_plan(task_id)
        assert "goal" in plan

        # Extract budget constraints from goal
        goal = plan["goal"]
        task_config = BoundaryConfig(
            max_cost_usd=goal["budget_max_cost_usd"],
            max_tokens=goal["budget_max_tokens"]
        )

        # Resolve config with task constraints
        resolver = ConfigResolver(boundary_yaml_path)
        config = resolver.resolve(
            task_id=task_id,
            task_config=task_config,
            environment="production"
        )

        # Verify goal budget limits are enforced (min logic)
        # boundary.yaml production has max_cost_usd=1.0, goal has 5.0
        # Should use 1.0 (stricter)
        assert config.max_cost_usd == 1.0

        # boundary.yaml production has max_tokens=500000, goal has 100000
        # Should use 100000 (stricter)
        assert config.max_tokens == 100000
