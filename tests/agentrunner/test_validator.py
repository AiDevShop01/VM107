"""
Tests for validation enforcement layer.

Tests format_validation_error() and validate_agent_output() functions
that provide runtime contract enforcement, plus ValidationExtension integration.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from core.contracts.validator import format_validation_error, validate_agent_output
from core.contracts import Hypothesis, BacktestResult, BacktestMetrics
from core.state_machine import AgentState
from extensions.python.message_loop_end._90_validation import ValidationExtension


class TestFormatValidationError:
    """Tests for format_validation_error() function."""

    def test_format_validation_error_extracts_fields(self):
        """Test that format_validation_error extracts field paths and constraint violations."""
        # Create invalid data that will trigger validation error
        invalid_data = {
            "hypothesis": "",  # Too short (min_length=10)
            "variables": [],  # Too few items (min_length=1)
            "confidence": 1.5,  # Out of range (le=1.0)
        }

        # Trigger validation error
        try:
            Hypothesis.model_validate(invalid_data)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            result = format_validation_error(e)

            # Check structure
            assert result["error"] == "validation_failed"
            assert "details" in result
            assert isinstance(result["details"], list)
            assert len(result["details"]) > 0

            # Check detail structure
            for detail in result["details"]:
                assert "field" in detail
                assert "type" in detail
                assert "message" in detail

    def test_format_validation_error_nested_field(self):
        """Test that nested field errors show dotted path (e.g., 'metrics.win_rate')."""
        # Create invalid backtest result with nested metrics error
        invalid_data = {
            "metrics": {
                "win_rate": "invalid",  # Should be float
                "rr": 2.0,
                "max_drawdown": 0.15,
            },
            "sample_size": 100,
            "confidence": 0.95,
        }

        try:
            BacktestResult.model_validate(invalid_data)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            result = format_validation_error(e)

            # Check that nested field path is dotted
            assert any(
                "metrics" in detail["field"]
                for detail in result["details"]
            )

    def test_format_validation_error_multiple_errors(self):
        """Test that multiple validation errors produce multiple detail entries."""
        invalid_data = {
            "hypothesis": "",  # Too short
            "variables": [],  # Too few items
            "confidence": 2.0,  # Out of range
        }

        try:
            Hypothesis.model_validate(invalid_data)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            result = format_validation_error(e)

            # Should have multiple errors
            assert len(result["details"]) >= 3

    def test_format_error_strips_internal_details(self):
        """Test that formatted error does not contain Python internals (security)."""
        invalid_data = {
            "hypothesis": "",
            "variables": [],
            "confidence": 2.0,
        }

        try:
            Hypothesis.model_validate(invalid_data)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            result = format_validation_error(e)

            # Convert to string to check for leaks
            result_str = str(result)

            # Should not contain Python class names or paths
            assert "core.contracts" not in result_str.lower()
            assert "pydantic" not in result_str.lower()
            assert "__" not in result_str  # No __init__, __main__, etc.


class TestValidateAgentOutput:
    """Tests for validate_agent_output() function."""

    def test_validate_agent_output_valid(self):
        """Test that validate_agent_output returns schema instance for valid data."""
        valid_data = {
            "hypothesis": "Price will increase when volume exceeds threshold",
            "variables": ["volume", "price"],
            "confidence": 0.85,
        }

        result = validate_agent_output("hypothesis", valid_data)

        # Should return Hypothesis instance
        assert isinstance(result, Hypothesis)
        assert result.hypothesis == valid_data["hypothesis"]
        assert result.variables == valid_data["variables"]
        assert result.confidence == valid_data["confidence"]

    def test_validate_agent_output_invalid(self):
        """Test that validate_agent_output raises ValidationError for invalid data."""
        invalid_data = {
            "hypothesis": "",  # Too short
            "variables": [],
            "confidence": 2.0,
        }

        with pytest.raises(ValidationError):
            validate_agent_output("hypothesis", invalid_data)

    def test_validate_agent_output_unknown_type(self):
        """Test that validate_agent_output raises ValueError for unknown type."""
        valid_data = {
            "hypothesis": "Some hypothesis",
            "variables": ["x"],
            "confidence": 0.5,
        }

        with pytest.raises(ValueError) as exc_info:
            validate_agent_output("unknown_type", valid_data)

        assert "unknown_type" in str(exc_info.value).lower()

    def test_validate_agent_output_returns_typed(self):
        """Test that returned object is instance of correct schema class."""
        # Test hypothesis
        hyp_data = {
            "hypothesis": "Price will increase",
            "variables": ["price"],
            "confidence": 0.75,
        }
        result = validate_agent_output("hypothesis", hyp_data)
        assert isinstance(result, Hypothesis)
        assert type(result).__name__ == "Hypothesis"

        # Test backtest_result
        bt_data = {
            "metrics": {
                "win_rate": 0.65,
                "rr": 2.5,
                "max_drawdown": 0.12,
            },
            "sample_size": 100,
            "confidence": 0.95,
        }
        result = validate_agent_output("backtest_result", bt_data)
        assert isinstance(result, BacktestResult)
        assert type(result).__name__ == "BacktestResult"


class TestValidationExtension:
    """Tests for ValidationExtension integration."""

    def test_validation_extension_skip_no_runner(self):
        """Test that extension gracefully skips when no runner exists."""
        # Create mock agent with no runner
        agent = MagicMock()
        agent.get_data.return_value = None

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Execute should not error
        import asyncio
        asyncio.run(ext.execute())

        # Should have called get_data to check for runner
        agent.get_data.assert_called_once_with("runner")

    def test_validation_extension_skip_not_running(self):
        """Test that extension skips validation when runner not in RUNNING state."""
        # Create mock agent with runner in PAUSED state
        agent = MagicMock()
        runner = MagicMock()
        runner.state = AgentState.PAUSED
        agent.get_data.return_value = runner

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Execute should skip validation
        import asyncio
        asyncio.run(ext.execute())

        # Should not have called runner.fail
        runner.fail.assert_not_called()

    def test_validation_extension_skip_no_contract_type(self):
        """Test that extension skips when response has no _contract_type."""
        # Create mock agent with runner in RUNNING state
        agent = MagicMock()
        agent.agent_name = "test_agent"
        runner = MagicMock()
        runner.state = AgentState.RUNNING
        agent.get_data.return_value = runner

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Response without _contract_type
        response = {"some_data": "value"}

        # Execute with response (no _contract_type key)
        import asyncio
        asyncio.run(ext.execute(response=response))

        # Should not have called runner.fail
        runner.fail.assert_not_called()

    @patch("extensions.python.message_loop_end._90_validation.logger")
    def test_validation_extension_success_logging(self, mock_logger):
        """Test that valid contract type logs success."""
        # Create mock agent with runner in RUNNING state
        agent = MagicMock()
        agent.agent_name = "test_agent"
        runner = MagicMock()
        runner.state = AgentState.RUNNING
        agent.get_data.return_value = runner

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Valid hypothesis data
        response = {
            "_contract_type": "hypothesis",
            "_contract_data": {
                "hypothesis": "Price will increase when volume is high",
                "variables": ["price", "volume"],
                "confidence": 0.85,
            },
        }

        # Execute with valid response
        import asyncio
        asyncio.run(ext.execute(response=response))

        # Should have logged success
        mock_logger.info.assert_called_once()
        log_call = mock_logger.info.call_args[0][0]
        log_data = json.loads(log_call)
        assert log_data["event"] == "validation_success"
        assert log_data["schema"] == "hypothesis"
        assert log_data["agent"] == "test_agent"

        # Should not have called runner.fail
        runner.fail.assert_not_called()

    @patch("extensions.python.message_loop_end._90_validation.logger")
    def test_validation_extension_failure_logs_and_fails(self, mock_logger):
        """Test that invalid data logs failure and calls runner.fail()."""
        # Create mock agent with runner in RUNNING state
        agent = MagicMock()
        agent.agent_name = "test_agent"
        runner = AsyncMock()
        runner.state = AgentState.RUNNING
        agent.get_data.return_value = runner

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Invalid hypothesis data (confidence out of range)
        response = {
            "_contract_type": "hypothesis",
            "_contract_data": {
                "hypothesis": "",  # Too short
                "variables": [],  # Too few
                "confidence": 2.0,  # Out of range
            },
        }

        # Execute with invalid response
        import asyncio
        asyncio.run(ext.execute(response=response))

        # Should have logged failure
        mock_logger.error.assert_called_once()
        log_call = mock_logger.error.call_args[0][0]
        log_data = json.loads(log_call)
        assert log_data["event"] == "validation_failed"
        assert log_data["schema"] == "hypothesis"
        assert "error_details" in log_data

        # Should have called runner.fail
        runner.fail.assert_called_once()
        fail_msg = runner.fail.call_args[0][0]
        assert "validation" in fail_msg.lower()

    @patch("extensions.python.message_loop_end._90_validation.logger")
    @patch("extensions.python.message_loop_end._90_validation.PrintStyle")
    def test_validation_extension_graceful_degradation(self, mock_print_style, mock_logger):
        """Test that exceptions in validation logic are caught and logged."""
        # Create mock agent that will cause an exception
        agent = MagicMock()
        agent.agent_name = "test_agent"
        agent.get_data.side_effect = Exception("Simulated error")

        # Create extension
        ext = ValidationExtension(agent=agent)

        # Execute should not raise exception
        import asyncio
        asyncio.run(ext.execute())

        # Should have logged error via PrintStyle
        mock_print_style.error.assert_called_once()
        error_msg = mock_print_style.error.call_args[0][0]
        assert "error" in error_msg.lower()
