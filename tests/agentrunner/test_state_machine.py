"""
Tests for AgentRunner state machine.

Validates:
- AgentState enum has exactly 6 members
- All valid transitions succeed
- Invalid transitions are blocked
- CANCELLED is terminal state
- validate_transition returns bool
- InvalidTransitionError captures from_state, to_state
"""
import pytest

from core.state_machine import (
    AgentState,
    ALLOWED_TRANSITIONS,
    validate_transition,
    InvalidTransitionError,
)


class TestAgentStateEnum:
    """Test AgentState enum definition."""

    def test_has_six_states(self):
        """AgentState must have exactly 6 members."""
        assert len(AgentState) == 6

    def test_has_idle_state(self):
        """AgentState must have IDLE state."""
        assert AgentState.IDLE.value == "idle"

    def test_has_running_state(self):
        """AgentState must have RUNNING state."""
        assert AgentState.RUNNING.value == "running"

    def test_has_paused_state(self):
        """AgentState must have PAUSED state."""
        assert AgentState.PAUSED.value == "paused"

    def test_has_cancelled_state(self):
        """AgentState must have CANCELLED state."""
        assert AgentState.CANCELLED.value == "cancelled"

    def test_has_complete_state(self):
        """AgentState must have COMPLETE state."""
        assert AgentState.COMPLETE.value == "complete"

    def test_has_failed_state(self):
        """AgentState must have FAILED state."""
        assert AgentState.FAILED.value == "failed"


class TestValidTransitions:
    """Test all valid state transitions."""

    def test_idle_to_running(self):
        """IDLE -> RUNNING is valid transition."""
        assert validate_transition(AgentState.IDLE, AgentState.RUNNING) is True

    def test_running_to_paused(self):
        """RUNNING -> PAUSED is valid transition."""
        assert validate_transition(AgentState.RUNNING, AgentState.PAUSED) is True

    def test_running_to_complete(self):
        """RUNNING -> COMPLETE is valid transition."""
        assert validate_transition(AgentState.RUNNING, AgentState.COMPLETE) is True

    def test_running_to_failed(self):
        """RUNNING -> FAILED is valid transition."""
        assert validate_transition(AgentState.RUNNING, AgentState.FAILED) is True

    def test_running_to_cancelled(self):
        """RUNNING -> CANCELLED is valid transition."""
        assert validate_transition(AgentState.RUNNING, AgentState.CANCELLED) is True

    def test_paused_to_running(self):
        """PAUSED -> RUNNING is valid transition."""
        assert validate_transition(AgentState.PAUSED, AgentState.RUNNING) is True

    def test_paused_to_cancelled(self):
        """PAUSED -> CANCELLED is valid transition."""
        assert validate_transition(AgentState.PAUSED, AgentState.CANCELLED) is True

    def test_failed_to_idle(self):
        """FAILED -> IDLE is valid transition (restart)."""
        assert validate_transition(AgentState.FAILED, AgentState.IDLE) is True

    def test_complete_to_idle(self):
        """COMPLETE -> IDLE is valid transition (new task)."""
        assert validate_transition(AgentState.COMPLETE, AgentState.IDLE) is True


class TestInvalidTransitions:
    """Test that invalid transitions are blocked."""

    def test_complete_to_running_blocked(self):
        """COMPLETE -> RUNNING is invalid."""
        assert validate_transition(AgentState.COMPLETE, AgentState.RUNNING) is False

    def test_cancelled_to_running_blocked(self):
        """CANCELLED -> RUNNING is invalid."""
        assert validate_transition(AgentState.CANCELLED, AgentState.RUNNING) is False

    def test_failed_to_running_blocked(self):
        """FAILED -> RUNNING is invalid (must go through IDLE)."""
        assert validate_transition(AgentState.FAILED, AgentState.RUNNING) is False

    def test_idle_to_complete_blocked(self):
        """IDLE -> COMPLETE is invalid (must run first)."""
        assert validate_transition(AgentState.IDLE, AgentState.COMPLETE) is False

    def test_idle_to_paused_blocked(self):
        """IDLE -> PAUSED is invalid (must run first)."""
        assert validate_transition(AgentState.IDLE, AgentState.PAUSED) is False

    def test_idle_to_failed_blocked(self):
        """IDLE -> FAILED is invalid (must run first)."""
        assert validate_transition(AgentState.IDLE, AgentState.FAILED) is False

    def test_idle_to_cancelled_blocked(self):
        """IDLE -> CANCELLED is invalid (must run first)."""
        assert validate_transition(AgentState.IDLE, AgentState.CANCELLED) is False


class TestTerminalStates:
    """Test terminal state behavior."""

    def test_cancelled_is_terminal(self):
        """CANCELLED state has no outgoing transitions."""
        assert ALLOWED_TRANSITIONS[AgentState.CANCELLED] == []

    def test_cancelled_to_idle_blocked(self):
        """CANCELLED -> IDLE is invalid (terminal state)."""
        assert validate_transition(AgentState.CANCELLED, AgentState.IDLE) is False

    def test_cancelled_to_running_blocked(self):
        """CANCELLED -> RUNNING is invalid (terminal state)."""
        assert validate_transition(AgentState.CANCELLED, AgentState.RUNNING) is False


class TestInvalidTransitionError:
    """Test InvalidTransitionError exception class."""

    def test_is_exception(self):
        """InvalidTransitionError must be an Exception subclass."""
        error = InvalidTransitionError(
            from_state=AgentState.COMPLETE,
            to_state=AgentState.RUNNING,
            reason="Complete is terminal"
        )
        assert isinstance(error, Exception)

    def test_captures_from_state(self):
        """InvalidTransitionError must capture from_state."""
        error = InvalidTransitionError(
            from_state=AgentState.COMPLETE,
            to_state=AgentState.RUNNING,
            reason="Test"
        )
        assert error.from_state == AgentState.COMPLETE

    def test_captures_to_state(self):
        """InvalidTransitionError must capture to_state."""
        error = InvalidTransitionError(
            from_state=AgentState.COMPLETE,
            to_state=AgentState.RUNNING,
            reason="Test"
        )
        assert error.to_state == AgentState.RUNNING

    def test_captures_reason(self):
        """InvalidTransitionError must capture reason."""
        error = InvalidTransitionError(
            from_state=AgentState.COMPLETE,
            to_state=AgentState.RUNNING,
            reason="Test reason"
        )
        assert error.reason == "Test reason"
