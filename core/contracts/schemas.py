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


class PreTradeEvaluation(BaseContract):
    """Formal pre-trade evaluation artifact (Phase 47.1 Wave 2).

    System fields (evaluation_id, trade_id, conversation_id, source_envelope_id,
    created_at, version, is_current, superseded_*, schema_version) default to
    empty/now/etc. so safe_parse on LLM-only JSON output validates cleanly. The
    runner injects them via model_copy(update={...}) after safe_parse succeeds.

    LLM-produced fields (no defaults — LLM must supply):
        instrument, direction, recommendation, confidence, score,
        check_results, reasoning_summary, risks, invalidations, next_action

    System-injected fields (defaults — LLM does NOT produce these):
        evaluation_id, trade_id, conversation_id, source_envelope_id,
        strategy_id, version, is_current, superseded_by, superseded_at,
        created_at, schema_version
    """

    # System-injected (defaults so LLM doesn't need to produce these)
    evaluation_id: str = ""
    trade_id: str = ""
    conversation_id: str = ""
    source_envelope_id: str = ""

    # Strategy linkage (nullable — handled per CONTEXT)
    strategy_id: Optional[str] = None

    # Setup identifiers (LLM confirms or echoes)
    instrument: str
    direction: Literal["long", "short", "neutral", "avoid"]

    # Decision (LLM)
    recommendation: Literal["enter", "wait", "avoid", "needs_more_confirmation"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    score: int = Field(..., ge=0, le=100)
    max_score: int = 100

    # Assessment (LLM)
    check_results: dict[str, Literal["pass", "fail", "unclear", "not_available"]]
    reasoning_summary: str
    risks: list[str]
    invalidations: list[str]
    next_action: str

    # Versioning (system)
    version: int = 1
    is_current: bool = True
    superseded_by: Optional[str] = None
    superseded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # schema_version (system — matches pattern in other contract schemas)
    schema_version: int = 1
