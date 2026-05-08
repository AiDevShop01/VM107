"""
Agent output schemas and A2A message envelope.

Defines the 5 core agent output types:
- Hypothesis: Idea agent output
- StrategySpec: Strategy agent output
- CodeModule: Code agent output
- BacktestResult: Backtester agent output
- Critique: Critic agent output

Plus the A2AMessage envelope for agent-to-agent communication.
"""
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator

from core.contracts.base import BaseContract

# Type aliases for Literal types
MessageType = Literal["hypothesis", "strategy_spec", "code_module", "backtest_result", "critique"]
Priority = Literal["low", "normal", "high", "urgent"]


class Hypothesis(BaseContract):
    """
    Hypothesis output from Idea Agent.

    Represents a testable market hypothesis with associated variables
    and confidence level.

    Phase 44 additions (additive — backward-compat defaults):
    - source_envelope_id: Optional[str] — provenance link to Idea Agent envelope
    - schema_version: int — strict version checking per CONTEXT.md § A2A Envelope Structure
    """

    hypothesis: str = Field(..., min_length=10)
    variables: list[str] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_envelope_id: Optional[str] = None
    schema_version: int = 1

    @field_validator("hypothesis")
    @classmethod
    def validate_hypothesis_not_blank(cls, v: str) -> str:
        """Reject whitespace-only hypothesis text."""
        if not v or v.strip() == "":
            raise ValueError("Hypothesis text cannot be blank or whitespace-only")
        return v

    @field_validator("variables")
    @classmethod
    def validate_no_duplicate_variables(cls, v: list[str]) -> list[str]:
        """Reject duplicate variable names."""
        if len(v) != len(set(v)):
            raise ValueError("Variable list contains duplicates")
        return v


class StrategySpec(BaseContract):
    """
    Strategy specification from Strategy Agent.

    Defines a trading strategy with features, rules, timeframes, and version.

    Phase 44 additions (additive — backward-compat defaults):
    - schema_version: int — strict version checking per CONTEXT.md § A2A Envelope Structure
    """

    name: str
    features: list[str] = Field(..., min_length=1)
    rules: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    version: str
    schema_version: int = 1


class CodeModule(BaseContract):
    """
    Code module from Code Agent.

    Contains generated code with module type, target VM, contract, and tests.
    """

    module_type: Literal["strategy", "feature"]
    target_vm: Literal["vm101", "vm102", "vm109"]
    contract: str
    code: str
    tests: str
    version: str


class BacktestMetrics(BaseContract):
    """
    Backtest performance metrics.

    Sub-model used within BacktestResult.
    """

    win_rate: float
    rr: float
    max_drawdown: float


class BacktestResult(BaseContract):
    """
    Backtest result from Backtester Agent.

    Contains performance metrics, sample size, and statistical confidence.
    Enforces cross-field validation for confidence vs sample size.
    """

    metrics: BacktestMetrics
    sample_size: int = Field(..., ge=1)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_confidence_vs_sample_size(self) -> "BacktestResult":
        """
        Enforce confidence limits based on sample size.

        Small samples (n < 30) cannot claim high confidence (> 0.7).
        This prevents over-confident results from insufficient data.
        """
        if self.sample_size < 30 and self.confidence > 0.7:
            raise ValueError(
                f"Confidence {self.confidence} too high for sample_size {self.sample_size}. "
                "Sample size < 30 requires confidence <= 0.7"
            )
        return self


class Critique(BaseContract):
    """
    Critique from Critic Agent.

    Provides decision (accept/reject/refine) with issues and suggestions.
    """

    decision: Literal["accept", "reject", "refine"]
    issues: list[str]
    suggestions: list[str]


class A2AMessage(BaseContract):
    """
    Agent-to-Agent message envelope.

    Wraps all agent outputs with metadata for routing, priority, and context.
    Validates message_type against allowed Literal values.
    Auto-generates UTC timestamp if not provided.
    """

    message_id: str
    from_agent: str
    to_agent: str
    message_type: MessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any]
    context: dict[str, Any] | None = None
    priority: Priority = "normal"
    requires_response: bool = True


# Phase 47.3 — PreTradeEvaluation, CategoryResult, and ConfidenceAdjustment
# moved to ``fingpt_core.contracts.agents.pre_trade_evaluation`` per Phase 39
# ContractTool discipline (typed contracts shared across VMs live in
# fingpt_core). This module re-exports the canonical names for backward
# compatibility — existing
# ``from core.contracts.schemas import PreTradeEvaluation`` imports keep
# working.
#
# Phase 47.3 additive fields on PreTradeEvaluation: confidence_adjustments,
# partial_context, category_results, framework_version (CF-4: default 0).
from fingpt_core.contracts.agents.pre_trade_evaluation import (  # noqa: E402,F401
    CategoryResult,
    ConfidenceAdjustment,
    PreTradeEvaluation,
)
