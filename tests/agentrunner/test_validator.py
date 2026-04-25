"""
Tests for validation enforcement layer.

Tests format_validation_error() and validate_agent_output() functions
that provide runtime contract enforcement.
"""
import pytest
from pydantic import ValidationError

from core.contracts.validator import format_validation_error, validate_agent_output
from core.contracts import Hypothesis, BacktestResult, BacktestMetrics


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
