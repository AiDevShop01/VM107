"""
Tests for AgentRunner data contracts and interface protocols.

Validates:
- ExecutionContext dataclass structure
- BoundaryStatus enum values
- StepResult dataclass structure
- StateTransition dataclass structure
- Protocol interface definitions with @runtime_checkable
- No-op implementations satisfy their protocol contracts
- No-op implementations return expected defaults
"""
import pytest

from core.execution_context import (
    ExecutionContext,
    BoundaryStatus,
    StepResult,
    StateTransition,
)
from core.interfaces import (
    TaskLedgerInterface,
    NoOpTaskLedger,
    ProgressLedgerInterface,
    NoOpProgressLedger,
    ExecutionBoundaryInterface,
    NoOpBoundary,
    StallDetectorInterface,
    NoOpStallDetector,
)


class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_is_dataclass(self):
        """ExecutionContext must be a dataclass."""
        ctx = ExecutionContext()
        assert hasattr(ctx, "__dataclass_fields__")

    def test_has_task_id_field(self):
        """ExecutionContext must have task_id field."""
        ctx = ExecutionContext(task_id="test-123")
        assert ctx.task_id == "test-123"

    def test_has_step_id_field(self):
        """ExecutionContext must have step_id field."""
        ctx = ExecutionContext(step_id="step-1")
        assert ctx.step_id == "step-1"

    def test_has_state_field(self):
        """ExecutionContext must have state field."""
        ctx = ExecutionContext(state="running")
        assert ctx.state == "running"

    def test_has_start_time_field(self):
        """ExecutionContext must have start_time field."""
        ctx = ExecutionContext(start_time=123.456)
        assert ctx.start_time == 123.456

    def test_has_step_count_field(self):
        """ExecutionContext must have step_count field."""
        ctx = ExecutionContext(step_count=5)
        assert ctx.step_count == 5

    def test_has_token_count_field(self):
        """ExecutionContext must have token_count field with default 0."""
        ctx = ExecutionContext()
        assert ctx.token_count == 0

    def test_has_cost_usd_field(self):
        """ExecutionContext must have cost_usd field with default 0.0."""
        ctx = ExecutionContext()
        assert ctx.cost_usd == 0.0

    def test_has_loop_iterations_field(self):
        """ExecutionContext must have loop_iterations field with default 0."""
        ctx = ExecutionContext()
        assert ctx.loop_iterations == 0

    def test_has_last_transition_field(self):
        """ExecutionContext must have last_transition field with default None."""
        ctx = ExecutionContext()
        assert ctx.last_transition is None


class TestBoundaryStatus:
    """Test BoundaryStatus enum."""

    def test_has_ok_value(self):
        """BoundaryStatus must have OK value."""
        assert BoundaryStatus.OK.value == "ok"

    def test_has_warning_value(self):
        """BoundaryStatus must have WARNING value."""
        assert BoundaryStatus.WARNING.value == "warning"

    def test_has_exceeded_value(self):
        """BoundaryStatus must have EXCEEDED value."""
        assert BoundaryStatus.EXCEEDED.value == "exceeded"


class TestStepResult:
    """Test StepResult dataclass."""

    def test_is_dataclass(self):
        """StepResult must be a dataclass."""
        result = StepResult(step_id="step-1", outcome="success")
        assert hasattr(result, "__dataclass_fields__")

    def test_has_step_id_field(self):
        """StepResult must have step_id field."""
        result = StepResult(step_id="step-1", outcome="success")
        assert result.step_id == "step-1"

    def test_has_outcome_field(self):
        """StepResult must have outcome field."""
        result = StepResult(step_id="step-1", outcome="success")
        assert result.outcome == "success"

    def test_has_metadata_field_with_default(self):
        """StepResult must have metadata field with default empty dict."""
        result = StepResult(step_id="step-1", outcome="success")
        assert result.metadata == {}


class TestStateTransition:
    """Test StateTransition dataclass."""

    def test_is_dataclass(self):
        """StateTransition must be a dataclass."""
        transition = StateTransition(
            event="start",
            from_state="idle",
            to_state="running",
            reason="Task started",
            timestamp="2026-04-24T12:00:00Z",
            agent_id="agent-1",
            context_id="ctx-1",
        )
        assert hasattr(transition, "__dataclass_fields__")

    def test_has_all_required_fields(self):
        """StateTransition must have all 7 required fields."""
        transition = StateTransition(
            event="start",
            from_state="idle",
            to_state="running",
            reason="Task started",
            timestamp="2026-04-24T12:00:00Z",
            agent_id="agent-1",
            context_id="ctx-1",
        )
        assert transition.event == "start"
        assert transition.from_state == "idle"
        assert transition.to_state == "running"
        assert transition.reason == "Task started"
        assert transition.timestamp == "2026-04-24T12:00:00Z"
        assert transition.agent_id == "agent-1"
        assert transition.context_id == "ctx-1"


class TestNoOpBoundary:
    """Test NoOpBoundary implementation."""

    @pytest.mark.asyncio
    async def test_check_returns_ok(self):
        """NoOpBoundary.check() must return BoundaryStatus.OK."""
        boundary = NoOpBoundary()
        ctx = ExecutionContext()
        status = await boundary.check(ctx)
        assert status == BoundaryStatus.OK

    def test_satisfies_interface(self):
        """NoOpBoundary must satisfy ExecutionBoundaryInterface."""
        boundary = NoOpBoundary()
        assert isinstance(boundary, ExecutionBoundaryInterface)


class TestNoOpTaskLedger:
    """Test NoOpTaskLedger implementation."""

    @pytest.mark.asyncio
    async def test_get_plan_returns_empty_dict(self):
        """NoOpTaskLedger.get_plan() must return empty dict."""
        ledger = NoOpTaskLedger()
        plan = await ledger.get_plan("task-1")
        assert plan == {}

    @pytest.mark.asyncio
    async def test_update_returns_none(self):
        """NoOpTaskLedger.update() must return None."""
        ledger = NoOpTaskLedger()
        result = await ledger.update("task-1", {"status": "done"})
        assert result is None

    def test_satisfies_interface(self):
        """NoOpTaskLedger must satisfy TaskLedgerInterface."""
        ledger = NoOpTaskLedger()
        assert isinstance(ledger, TaskLedgerInterface)


class TestNoOpProgressLedger:
    """Test NoOpProgressLedger implementation."""

    @pytest.mark.asyncio
    async def test_get_next_action_returns_none(self):
        """NoOpProgressLedger.get_next_action() must return None."""
        ledger = NoOpProgressLedger()
        ctx = ExecutionContext()
        action = await ledger.get_next_action(ctx)
        assert action is None

    @pytest.mark.asyncio
    async def test_record_step_returns_none(self):
        """NoOpProgressLedger.record_step() must return None."""
        ledger = NoOpProgressLedger()
        result = StepResult(step_id="step-1", outcome="success")
        ret = await ledger.record_step(result)
        assert ret is None

    def test_satisfies_interface(self):
        """NoOpProgressLedger must satisfy ProgressLedgerInterface."""
        ledger = NoOpProgressLedger()
        assert isinstance(ledger, ProgressLedgerInterface)


class TestNoOpStallDetector:
    """Test NoOpStallDetector implementation."""

    @pytest.mark.asyncio
    async def test_check_returns_false(self):
        """NoOpStallDetector.check() must return False."""
        detector = NoOpStallDetector()
        ctx = ExecutionContext()
        is_stalled = await detector.check(ctx)
        assert is_stalled is False

    @pytest.mark.asyncio
    async def test_trigger_replan_returns_none(self):
        """NoOpStallDetector.trigger_replan() must return None."""
        detector = NoOpStallDetector()
        result = await detector.trigger_replan()
        assert result is None

    def test_satisfies_interface(self):
        """NoOpStallDetector must satisfy StallDetectorInterface."""
        detector = NoOpStallDetector()
        assert isinstance(detector, StallDetectorInterface)
