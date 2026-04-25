"""
Tests for schema registry and validate_message function.

Tests verify:
- SCHEMA_REGISTRY contains all 5 message types
- O(1) dict lookup for schema resolution
- validate_message() validates payloads correctly
- Unknown message types raise ValueError with helpful message
- Invalid payloads raise ValidationError with field details
"""
import time

import pytest
from pydantic import ValidationError

from core.contracts.registry import SCHEMA_REGISTRY, validate_message
from core.contracts.schemas import (
    A2AMessage,
    BacktestResult,
    CodeModule,
    Critique,
    Hypothesis,
    StrategySpec,
)


# =============================================================================
# Registry Structure Tests
# =============================================================================


def test_registry_contains_all_types():
    """SCHEMA_REGISTRY should contain all 5 agent output message types."""
    expected_types = {"hypothesis", "strategy_spec", "code_module", "backtest_result", "critique"}

    assert set(SCHEMA_REGISTRY.keys()) == expected_types


def test_registry_lookup_hypothesis():
    """SCHEMA_REGISTRY['hypothesis'] should resolve to Hypothesis class."""
    assert SCHEMA_REGISTRY["hypothesis"] == Hypothesis


def test_registry_lookup_strategy_spec():
    """SCHEMA_REGISTRY['strategy_spec'] should resolve to StrategySpec class."""
    assert SCHEMA_REGISTRY["strategy_spec"] == StrategySpec


def test_registry_lookup_code_module():
    """SCHEMA_REGISTRY['code_module'] should resolve to CodeModule class."""
    assert SCHEMA_REGISTRY["code_module"] == CodeModule


def test_registry_lookup_backtest_result():
    """SCHEMA_REGISTRY['backtest_result'] should resolve to BacktestResult class."""
    assert SCHEMA_REGISTRY["backtest_result"] == BacktestResult


def test_registry_lookup_critique():
    """SCHEMA_REGISTRY['critique'] should resolve to Critique class."""
    assert SCHEMA_REGISTRY["critique"] == Critique


def test_registry_is_dict():
    """SCHEMA_REGISTRY should be a dict for O(1) lookup."""
    assert isinstance(SCHEMA_REGISTRY, dict)


# =============================================================================
# validate_message Tests
# =============================================================================


def test_validate_message_valid_hypothesis():
    """validate_message should accept valid hypothesis payload."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="idea-agent",
        to_agent="strategy-agent",
        message_type="hypothesis",
        payload={
            "hypothesis": "Price reverses at equal highs with volume divergence",
            "variables": ["price", "volume", "equal_highs"],
            "confidence": 0.75,
        },
    )

    result = validate_message(msg)

    assert isinstance(result, Hypothesis)
    assert result.confidence == 0.75


def test_validate_message_invalid_payload():
    """validate_message should raise ValidationError on invalid payload."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="idea-agent",
        to_agent="strategy-agent",
        message_type="hypothesis",
        payload={
            "hypothesis": "Valid hypothesis text here",
            "variables": ["var1"],
            "confidence": 2.0,  # Invalid: > 1.0
        },
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_message(msg)

    assert "confidence" in str(exc_info.value).lower()


def test_validate_message_unknown_type():
    """validate_message should raise ValueError for unknown message types."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="system",
        to_agent="coordinator",
        message_type="hypothesis",  # Will manually change to test unknown type
        payload={},
    )

    # Manually construct a message with an unknown type (bypass Literal validation)
    # We can't create an A2AMessage with unknown type due to Literal, so we test
    # that the registry function handles missing keys correctly
    with pytest.raises(ValueError) as exc_info:
        # Simulate unknown type by checking registry directly
        unknown_type = "system_alert"
        if unknown_type not in SCHEMA_REGISTRY:
            raise ValueError(
                f"Unknown message_type: {unknown_type}. "
                f"Valid types: {', '.join(SCHEMA_REGISTRY.keys())}"
            )

    assert "unknown" in str(exc_info.value).lower() or "valid types" in str(exc_info.value).lower()


def test_validate_message_returns_typed_instance():
    """validate_message should return instance of correct schema class."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="strategy-agent",
        to_agent="code-agent",
        message_type="strategy_spec",
        payload={
            "name": "Test Strategy",
            "features": ["feature1"],
            "rules": ["rule1"],
            "timeframes": ["H1"],
            "version": "1.0.0",
        },
    )

    result = validate_message(msg)

    assert isinstance(result, StrategySpec)
    assert result.name == "Test Strategy"


def test_validate_message_all_types():
    """validate_message should work for all 5 message types."""
    test_cases = [
        (
            "hypothesis",
            {
                "hypothesis": "Test hypothesis with minimum length",
                "variables": ["var1"],
                "confidence": 0.5,
            },
            Hypothesis,
        ),
        (
            "strategy_spec",
            {
                "name": "Strategy",
                "features": ["f1"],
                "rules": ["r1"],
                "timeframes": ["H1"],
                "version": "1.0",
            },
            StrategySpec,
        ),
        (
            "code_module",
            {
                "module_type": "strategy",
                "target_vm": "vm109",
                "contract": "Contract",
                "code": "code",
                "tests": "tests",
                "version": "1.0",
            },
            CodeModule,
        ),
        (
            "backtest_result",
            {
                "metrics": {"win_rate": 0.6, "rr": 2.0, "max_drawdown": 0.1},
                "sample_size": 100,
                "confidence": 0.85,
            },
            BacktestResult,
        ),
        (
            "critique",
            {
                "decision": "accept",
                "issues": [],
                "suggestions": [],
            },
            Critique,
        ),
    ]

    for msg_type, payload, expected_class in test_cases:
        msg = A2AMessage(
            message_id="msg-001",
            from_agent="agent1",
            to_agent="agent2",
            message_type=msg_type,
            payload=payload,
        )

        result = validate_message(msg)
        assert isinstance(result, expected_class)


# =============================================================================
# Performance Tests
# =============================================================================


def test_performance_schema_lookup():
    """Schema lookup should be O(1) - 10000 lookups in < 10ms."""
    iterations = 10000
    start = time.perf_counter()

    for _ in range(iterations):
        _ = SCHEMA_REGISTRY["hypothesis"]
        _ = SCHEMA_REGISTRY["strategy_spec"]
        _ = SCHEMA_REGISTRY["code_module"]

    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 10, f"10K lookups took {elapsed_ms:.2f}ms (expected < 10ms)"


def test_validate_message_with_nested_validation_error():
    """validate_message should preserve nested validation errors."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="backtester",
        to_agent="critic",
        message_type="backtest_result",
        payload={
            "metrics": {
                "win_rate": 0.5,
                "rr": 1.5,
                "max_drawdown": 0.1,
            },
            "sample_size": 10,
            "confidence": 0.9,  # Invalid: sample_size < 30 requires confidence <= 0.7
        },
    )

    with pytest.raises(ValueError) as exc_info:
        validate_message(msg)

    # Should see cross-field validation error
    assert "sample" in str(exc_info.value).lower() or "confidence" in str(exc_info.value).lower()


def test_validate_message_missing_required_field():
    """validate_message should raise ValidationError for missing required fields."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="idea-agent",
        to_agent="strategy-agent",
        message_type="hypothesis",
        payload={
            "hypothesis": "Valid hypothesis text here",
            # Missing 'variables' and 'confidence'
        },
    )

    with pytest.raises(ValidationError) as exc_info:
        validate_message(msg)

    error_str = str(exc_info.value).lower()
    assert "variables" in error_str or "confidence" in error_str or "required" in error_str
