"""
Tests for all agent output schemas and A2AMessage envelope.

Tests verify field validation, bounds checking, and cross-field constraints.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.contracts.schemas import (
    A2AMessage,
    BacktestMetrics,
    BacktestResult,
    CodeModule,
    Critique,
    Hypothesis,
    MessageType,
    Priority,
    StrategySpec,
)


# =============================================================================
# Hypothesis Tests
# =============================================================================


def test_valid_hypothesis():
    """Hypothesis should accept all valid fields."""
    h = Hypothesis(
        hypothesis="Price tends to reverse at equal highs when volume diverges",
        variables=["price", "volume", "equal_highs"],
        confidence=0.75,
    )

    assert h.hypothesis == "Price tends to reverse at equal highs when volume diverges"
    assert h.variables == ["price", "volume", "equal_highs"]
    assert h.confidence == 0.75


def test_confidence_lower_bound():
    """Hypothesis should reject confidence < 0.0."""
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            hypothesis="Test hypothesis with minimum length",
            variables=["var1"],
            confidence=-0.1,
        )

    assert "confidence" in str(exc_info.value).lower()


def test_confidence_upper_bound():
    """Hypothesis should reject confidence > 1.0."""
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            hypothesis="Test hypothesis with minimum length",
            variables=["var1"],
            confidence=1.1,
        )

    assert "confidence" in str(exc_info.value).lower()


def test_confidence_at_bounds():
    """Hypothesis should accept confidence at exact bounds 0.0 and 1.0."""
    h1 = Hypothesis(
        hypothesis="Test hypothesis with minimum length",
        variables=["var1"],
        confidence=0.0,
    )
    assert h1.confidence == 0.0

    h2 = Hypothesis(
        hypothesis="Test hypothesis with minimum length",
        variables=["var1"],
        confidence=1.0,
    )
    assert h2.confidence == 1.0


def test_empty_hypothesis_string():
    """Hypothesis should reject whitespace-only hypothesis text."""
    # Whitespace-only string fails min_length validation (caught before field_validator)
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            hypothesis="   ",
            variables=["var1"],
            confidence=0.5,
        )

    # Accept either our custom validator message or Pydantic's min_length error
    error_str = str(exc_info.value).lower()
    assert "whitespace" in error_str or "blank" in error_str or "at least 10 characters" in error_str


def test_short_hypothesis():
    """Hypothesis should reject hypothesis text < 10 characters."""
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            hypothesis="Short",
            variables=["var1"],
            confidence=0.5,
        )

    assert "hypothesis" in str(exc_info.value).lower()


def test_empty_variables():
    """Hypothesis should reject empty variables list."""
    with pytest.raises(ValidationError) as exc_info:
        Hypothesis(
            hypothesis="Test hypothesis with minimum length",
            variables=[],
            confidence=0.5,
        )

    assert "variables" in str(exc_info.value).lower()


def test_duplicate_variables():
    """Hypothesis should reject duplicate variable names."""
    with pytest.raises(ValueError) as exc_info:
        Hypothesis(
            hypothesis="Test hypothesis with minimum length",
            variables=["var1", "var2", "var1"],
            confidence=0.5,
        )

    assert "duplicate" in str(exc_info.value).lower()


# =============================================================================
# StrategySpec Tests
# =============================================================================


def test_valid_strategy_spec():
    """StrategySpec should accept all valid fields.

    Phase 48 Plan 48-01: strategy_family REQUIRED. Added BREAKOUT here.
    """
    from core.contracts.schemas import StrategyFamily

    spec = StrategySpec(
        name="Liquidity Reversal Strategy",
        features=["equal_highs", "volume_delta", "fvg_strength"],
        rules=["Entry: FVG sweep with volume confirmation", "Exit: 2:1 RR"],
        timeframes=["M15", "H1"],
        version="1.0.0",
        strategy_family=StrategyFamily.MEAN_REVERSION,
    )

    assert spec.name == "Liquidity Reversal Strategy"
    assert len(spec.features) == 3
    assert len(spec.rules) == 2
    assert spec.version == "1.0.0"


def test_empty_features():
    """StrategySpec should reject empty features list."""
    with pytest.raises(ValidationError) as exc_info:
        StrategySpec(
            name="Test Strategy",
            features=[],
            rules=["rule1"],
            timeframes=["H1"],
            version="1.0.0",
        )

    assert "features" in str(exc_info.value).lower()


def test_empty_rules():
    """StrategySpec should reject empty rules list."""
    with pytest.raises(ValidationError) as exc_info:
        StrategySpec(
            name="Test Strategy",
            features=["feature1"],
            rules=[],
            timeframes=["H1"],
            version="1.0.0",
        )

    assert "rules" in str(exc_info.value).lower()


# =============================================================================
# CodeModule Tests
# =============================================================================


def test_valid_code_module():
    """CodeModule should accept all valid fields."""
    module = CodeModule(
        module_type="strategy",
        target_vm="vm109",
        contract="StrategyInterface",
        code="def execute(): pass",
        tests="def test_execute(): pass",
        version="1.0.0",
    )

    assert module.module_type == "strategy"
    assert module.target_vm == "vm109"
    assert module.version == "1.0.0"


def test_invalid_module_type():
    """CodeModule should reject invalid module_type."""
    with pytest.raises(ValidationError) as exc_info:
        CodeModule(
            module_type="unknown",
            target_vm="vm109",
            contract="Interface",
            code="code",
            tests="tests",
            version="1.0.0",
        )

    assert "module_type" in str(exc_info.value).lower()


def test_invalid_target_vm():
    """CodeModule should reject invalid target_vm."""
    with pytest.raises(ValidationError) as exc_info:
        CodeModule(
            module_type="strategy",
            target_vm="vm999",
            contract="Interface",
            code="code",
            tests="tests",
            version="1.0.0",
        )

    assert "target_vm" in str(exc_info.value).lower()


def test_valid_literals():
    """CodeModule should accept all valid Literal values."""
    # Test all module_type values
    for module_type in ["strategy", "feature"]:
        module = CodeModule(
            module_type=module_type,
            target_vm="vm101",
            contract="Interface",
            code="code",
            tests="tests",
            version="1.0.0",
        )
        assert module.module_type == module_type

    # Test all target_vm values
    for target_vm in ["vm101", "vm102", "vm109"]:
        module = CodeModule(
            module_type="strategy",
            target_vm=target_vm,
            contract="Interface",
            code="code",
            tests="tests",
            version="1.0.0",
        )
        assert module.target_vm == target_vm


# =============================================================================
# BacktestResult Tests
# =============================================================================


def test_valid_backtest_result():
    """BacktestResult should accept nested BacktestMetrics."""
    result = BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.65,
            rr=2.5,
            max_drawdown=0.12,
        ),
        sample_size=100,
        confidence=0.85,
    )

    assert result.metrics.win_rate == 0.65
    assert result.sample_size == 100
    assert result.confidence == 0.85


def test_negative_sample_size():
    """BacktestResult should reject sample_size <= 0."""
    with pytest.raises(ValidationError) as exc_info:
        BacktestResult(
            metrics=BacktestMetrics(win_rate=0.5, rr=1.5, max_drawdown=0.1),
            sample_size=0,
            confidence=0.5,
        )

    assert "sample_size" in str(exc_info.value).lower()


def test_confidence_sample_size_cross_validation():
    """BacktestResult should reject high confidence with low sample size."""
    with pytest.raises(ValueError) as exc_info:
        BacktestResult(
            metrics=BacktestMetrics(win_rate=0.5, rr=1.5, max_drawdown=0.1),
            sample_size=10,
            confidence=0.9,
        )

    assert "sample" in str(exc_info.value).lower() and "confidence" in str(exc_info.value).lower()


def test_low_confidence_low_sample_accepted():
    """BacktestResult should accept low confidence with low sample size."""
    result = BacktestResult(
        metrics=BacktestMetrics(win_rate=0.5, rr=1.5, max_drawdown=0.1),
        sample_size=10,
        confidence=0.6,
    )

    assert result.sample_size == 10
    assert result.confidence == 0.6


def test_high_confidence_high_sample_accepted():
    """BacktestResult should accept high confidence with high sample size."""
    result = BacktestResult(
        metrics=BacktestMetrics(win_rate=0.5, rr=1.5, max_drawdown=0.1),
        sample_size=100,
        confidence=0.95,
    )

    assert result.sample_size == 100
    assert result.confidence == 0.95


# =============================================================================
# Critique Tests
# =============================================================================


def test_valid_critique():
    """Critique should accept all three valid decisions."""
    for decision in ["accept", "reject", "refine"]:
        critique = Critique(
            decision=decision,
            issues=["Issue 1"],
            suggestions=["Suggestion 1"],
        )
        assert critique.decision == decision


def test_invalid_decision():
    """Critique should reject invalid decision values."""
    with pytest.raises(ValidationError) as exc_info:
        Critique(
            decision="maybe",
            issues=[],
            suggestions=[],
        )

    assert "decision" in str(exc_info.value).lower()


def test_empty_lists_allowed():
    """Critique should allow empty issues and suggestions lists."""
    critique = Critique(
        decision="accept",
        issues=[],
        suggestions=[],
    )

    assert critique.issues == []
    assert critique.suggestions == []


# =============================================================================
# A2AMessage Tests
# =============================================================================


def test_valid_a2a_message():
    """A2AMessage should accept all valid fields."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="idea-agent",
        to_agent="strategy-agent",
        message_type="hypothesis",
        payload={"test": "data"},
        context={"session_id": "123"},
        priority="high",
        requires_response=True,
    )

    assert msg.message_id == "msg-001"
    assert msg.from_agent == "idea-agent"
    assert msg.message_type == "hypothesis"
    assert msg.priority == "high"


def test_invalid_message_type():
    """A2AMessage should reject invalid message_type."""
    with pytest.raises(ValidationError) as exc_info:
        A2AMessage(
            message_id="msg-001",
            from_agent="agent1",
            to_agent="agent2",
            message_type="unknown",
            payload={},
        )

    assert "message_type" in str(exc_info.value).lower()


def test_default_priority():
    """A2AMessage should default priority to 'normal'."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="agent1",
        to_agent="agent2",
        message_type="hypothesis",
        payload={},
    )

    assert msg.priority == "normal"


def test_default_requires_response():
    """A2AMessage should default requires_response to True."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="agent1",
        to_agent="agent2",
        message_type="hypothesis",
        payload={},
    )

    assert msg.requires_response is True


def test_timestamp_auto_generated():
    """A2AMessage should auto-generate timestamp if not provided."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="agent1",
        to_agent="agent2",
        message_type="hypothesis",
        payload={},
    )

    assert isinstance(msg.timestamp, datetime)
    assert msg.timestamp.tzinfo == timezone.utc


def test_optional_context():
    """A2AMessage should accept None for context."""
    msg = A2AMessage(
        message_id="msg-001",
        from_agent="agent1",
        to_agent="agent2",
        message_type="hypothesis",
        payload={},
        context=None,
    )

    assert msg.context is None


def test_valid_priority_values():
    """A2AMessage should accept all valid Priority values."""
    for priority in ["low", "normal", "high", "urgent"]:
        msg = A2AMessage(
            message_id="msg-001",
            from_agent="agent1",
            to_agent="agent2",
            message_type="hypothesis",
            payload={},
            priority=priority,
        )
        assert msg.priority == priority


def test_valid_message_types():
    """A2AMessage should accept all valid MessageType values."""
    valid_types = ["hypothesis", "strategy_spec", "code_module", "backtest_result", "critique"]

    for msg_type in valid_types:
        msg = A2AMessage(
            message_id="msg-001",
            from_agent="agent1",
            to_agent="agent2",
            message_type=msg_type,
            payload={},
        )
        assert msg.message_type == msg_type
