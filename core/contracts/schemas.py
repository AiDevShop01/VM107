"""
Agent output schemas and A2A message envelope.

Defines the 5 core agent output types:
- Hypothesis: Idea agent output
- StrategySpec: Strategy agent output
- CodeModule: Code agent output
- BacktestResult: Backtester agent output
- Critique: Critic agent output

Plus the A2AMessage envelope for agent-to-agent communication.

Phase 48 additions (Plan 48-01):
- 7 new Pydantic models: CriticVerdict, RefinementTarget,
  RefinementContextEnvelope, RefinementLoopState,
  DeterministicAcceptanceResult, ExecutionCost, RefinementOutcome.
- 1 new minimal model: BuildReport (Phase 45 deferral closed here — needed by
  Plan 48-01 Task 1.3 wrappers).
- 6 new enums: StrategyFamily, FieldMutability, TerminationReason,
  AcceptanceClassification, RefinementTaskState, CanonicalIssueId.
- StrategySpec gains REQUIRED strategy_family enum field + FieldMutability
  per-field metadata via Field(json_schema_extra=...).
- Phase 37 Critique class preserved verbatim — see docstring on Critique.
"""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator

from core.contracts.base import BaseContract

# Type aliases for Literal types
MessageType = Literal["hypothesis", "strategy_spec", "code_module", "backtest_result", "critique"]
Priority = Literal["low", "normal", "high", "urgent"]


# =============================================================================
# Phase 48 enums (Plan 48-01)
# =============================================================================


class StrategyFamily(StrEnum):
    """Phase 48 § Decision 1 — locked starter family taxonomy.

    Extension governance: new family requires planning-time decision (not
    LLM-emitted). Family scoping drives per-family Critic skill overlay.
    """

    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    AUCTION_ROTATION = "AUCTION_ROTATION"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"


class FieldMutability(StrEnum):
    """Phase 48 § Decision 10 — StrategySpec field-level mutability buckets.

    Identity scorer (Plan 04) reads these via Pydantic Field json_schema_extra
    to weight the structured diff.

    - IMMUTABLE_CORE: changing this terminates the loop (e.g., strategy_family).
    - REFINABLE: structural-but-tunable (e.g., entry condition class).
    - MINOR_TUNING: parameter values (e.g., ATR multipliers, stop widths).
    """

    IMMUTABLE_CORE = "IMMUTABLE_CORE"
    REFINABLE = "REFINABLE"
    MINOR_TUNING = "MINOR_TUNING"


class TerminationReason(StrEnum):
    """Phase 48 § Decision 4 — 9 base states + 5 BUILD_FAILURE sub-states (14 total).

    Planner discretion (CONTEXT.md § Claude's Discretion): BUILD_FAILURE is
    kept as the top-level bucket emitted by orchestrator-level fall-through;
    the 5 sub-states (CRITIC_DEGRADED / STRATEGY_DEGRADED / CODE_DEGRADED /
    BUILD_FAILED / BACKTEST_DEGRADED) provide replay-archaeology granularity
    for pipeline-stage degradation paths.
    """

    # --- 9 base states ---
    ACCEPTED = "ACCEPTED"
    CRITIC_REJECT = "CRITIC_REJECT"
    HARD_VETO = "HARD_VETO"
    IDENTITY_DRIFT = "IDENTITY_DRIFT"
    CONVERGENCE_STALL = "CONVERGENCE_STALL"
    BUDGET_EXCEEDED_ITERATION = "BUDGET_EXCEEDED_ITERATION"
    BUDGET_EXCEEDED_LOOP = "BUDGET_EXCEEDED_LOOP"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    BUILD_FAILURE = "BUILD_FAILURE"

    # --- 5 BUILD_FAILURE sub-states (planner discretion) ---
    CRITIC_DEGRADED = "CRITIC_DEGRADED"
    STRATEGY_DEGRADED = "STRATEGY_DEGRADED"
    CODE_DEGRADED = "CODE_DEGRADED"
    BUILD_FAILED = "BUILD_FAILED"
    BACKTEST_DEGRADED = "BACKTEST_DEGRADED"


class AcceptanceClassification(StrEnum):
    """Phase 48 § Decision 8 — deterministic acceptance floor outcomes."""

    HARD_REJECT = "HARD_REJECT"
    REFINABLE_WEAKNESS = "REFINABLE_WEAKNESS"
    CRITIC_ELIGIBLE = "CRITIC_ELIGIBLE"


class RefinementTaskState(StrEnum):
    """Phase 48 § Decision 17 — async task state machine for /pipeline/refine."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REFINING = "REFINING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CONVERGENCE_STALL = "CONVERGENCE_STALL"
    IDENTITY_DRIFT = "IDENTITY_DRIFT"


class CanonicalIssueId(StrEnum):
    """Phase 48 § Decision 7 — canonical refinement-issue taxonomy.

    Convergence detection compares (scope, canonical_issue_id, issue_type)
    tuple equality across iterations. Stable IDs prevent LLM-prose drift from
    breaking convergence semantics.

    Extension governance: new IDs require planning-time decision (NO
    LLM-emitted free-form IDs). RESEARCH.md § Open Question 5 seeds 15 starter
    IDs covering most ROBUSTNESS critiques.
    """

    SAMPLE_SIZE_TOO_SMALL = "SAMPLE_SIZE_TOO_SMALL"
    REGIME_CONCENTRATION_HIGH = "REGIME_CONCENTRATION_HIGH"
    PARAMETER_SENSITIVITY_HIGH = "PARAMETER_SENSITIVITY_HIGH"
    WIN_RATE_BELOW_FLOOR = "WIN_RATE_BELOW_FLOOR"
    MAX_DRAWDOWN_NEAR_FLOOR = "MAX_DRAWDOWN_NEAR_FLOOR"
    PROFIT_FACTOR_NEAR_FLOOR = "PROFIT_FACTOR_NEAR_FLOOR"
    CONFIRMATION_BARS_INSUFFICIENT = "CONFIRMATION_BARS_INSUFFICIENT"
    STOP_WIDTH_TOO_TIGHT = "STOP_WIDTH_TOO_TIGHT"
    STOP_WIDTH_TOO_WIDE = "STOP_WIDTH_TOO_WIDE"
    EXIT_TIMING_DELAYED = "EXIT_TIMING_DELAYED"
    ENTRY_FILTER_TOO_LOOSE = "ENTRY_FILTER_TOO_LOOSE"
    ENTRY_FILTER_TOO_STRICT = "ENTRY_FILTER_TOO_STRICT"
    OVERFIT_SIGNATURE = "OVERFIT_SIGNATURE"
    REGIME_FRAGILITY = "REGIME_FRAGILITY"
    EXPECTANCY_UNSTABLE = "EXPECTANCY_UNSTABLE"


# =============================================================================
# Phase 37 / 44 / 45 core schemas (preserved)
# =============================================================================


class Hypothesis(BaseContract):
    """
    Hypothesis output from Idea Agent.

    Represents a testable market hypothesis with associated variables
    and confidence level.

    Phase 44 additions (additive — backward-compat defaults):
    - source_envelope_id: Optional[str] — provenance link to Idea Agent envelope
    - schema_version: int — strict version checking per CONTEXT.md § A2A Envelope Structure

    Phase 48 § Decision 6: Hypothesis is IMMUTABLE WORM — never mutated, overwritten,
    or "refined." BaseContract enforces this via frozen=True. New idea = new Hypothesis.
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

    Phase 48 additions (Plan 48-01):
    - strategy_family: StrategyFamily REQUIRED enum (breaking-but-additive — every
      newly produced StrategySpec must carry a family. Pre-Phase-48 Mongo docs
      without this field fail validation by design; the migration was explicitly
      accepted in CONTEXT § Decision 1).
    - FieldMutability metadata on every field via Field(json_schema_extra={"mutability": ...}).
      Plan 04 identity scorer reads this to weight the structured diff.
    """

    name: str = Field(
        ...,
        json_schema_extra={"mutability": FieldMutability.IMMUTABLE_CORE.value},
    )
    features: list[str] = Field(
        ...,
        min_length=1,
        json_schema_extra={"mutability": FieldMutability.REFINABLE.value},
    )
    rules: list[str] = Field(
        ...,
        min_length=1,
        json_schema_extra={"mutability": FieldMutability.REFINABLE.value},
    )
    timeframes: list[str] = Field(
        ...,
        min_length=1,
        json_schema_extra={"mutability": FieldMutability.IMMUTABLE_CORE.value},
    )
    version: str = Field(
        ...,
        json_schema_extra={"mutability": FieldMutability.MINOR_TUNING.value},
    )
    strategy_family: StrategyFamily = Field(
        ...,
        json_schema_extra={"mutability": FieldMutability.IMMUTABLE_CORE.value},
    )
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


class BuildReport(BaseContract):
    """
    Build report from the deterministic Build Agent.

    Phase 48 Plan 48-01 — minimal shape shipped here to close the Phase 45
    deferral. Plan 48-03+ may extend with diagnostic structure (compile errors,
    static-analysis findings, test-import errors). For now this is the
    smallest-possible typed surface that Plan 48-01 Task 1.3 run_build can
    return.

    Phase 45 / Phase 48 § Decision 14: build_agent is a pure-Python service —
    NO LLM call, NO retry — so the report shape is deterministic.
    """

    status: Literal["success", "failure"]
    artifact_id: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    schema_version: int = 1


class Critique(BaseContract):
    """
    Critique from Critic Agent — Phase 37 generic critique.

    Phase 37 introduced this as a generic `decision ∈ {accept, reject, refine}`
    shape with prose `issues` / `suggestions`. **Phase 48 introduces
    `CriticVerdict` for refinement loops — a strict superset with structured
    `refinement_targets`, `confidence`, `failure_modes`, `loaded_skills`,
    and replay provenance. Do NOT use `Critique` for refinement-loop paths;
    use `CriticVerdict` instead.**

    Phase 37 callers continue to use this shape. Both classes coexist
    deliberately (CONTEXT.md § Decision 1 + Plan 00 Decision F).
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


# =============================================================================
# Phase 48 Plan 48-01 — 7 new typed schemas
# =============================================================================


def _build_target_field_vocabulary() -> frozenset[str]:
    """Module-level cache: controlled vocabulary for RefinementTarget.target_field.

    Built ONCE at module-init time from StrategySpec.model_fields ∪ CodeModule.model_fields.
    Dotted-path enumeration is also supported (e.g., "metrics.win_rate") — the
    validator checks dotted prefixes against this set.
    """
    fields: set[str] = set()
    fields.update(StrategySpec.model_fields.keys())
    fields.update(CodeModule.model_fields.keys())
    # Allow nested BacktestMetrics fields too (Plan 06 critic frequently references these).
    for field_name in BacktestMetrics.model_fields:
        fields.add(f"metrics.{field_name}")
    return frozenset(fields)


_TARGET_FIELD_VOCABULARY: frozenset[str] = _build_target_field_vocabulary()


class RefinementTarget(BaseContract):
    """Phase 48 § Decision 1 + 5 — structured refinement target.

    Critic emits RefinementTargets (never prose) so the orchestrator can route
    each target to the correct regeneration path (Strategy Agent for
    STRATEGY_SPEC scope, Code Agent for CODE_MODULE scope). The
    (scope, canonical_issue_id, issue_type) tuple is the convergence-detection
    key (Decision 7).
    """

    scope: Literal["STRATEGY_SPEC", "CODE_MODULE"]
    canonical_issue_id: CanonicalIssueId
    target_field: str
    issue: str
    issue_type: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    suggested_change: str
    source_critic_verdict_id: str
    schema_version: int = 1

    @field_validator("target_field")
    @classmethod
    def validate_target_field_in_vocabulary(cls, v: str) -> str:
        """Reject unknown target_field names (controlled vocabulary discipline).

        Allowed: any top-level field name on StrategySpec or CodeModule, plus
        explicitly-enumerated nested paths (e.g., "metrics.win_rate"). Dotted
        prefix match is also allowed for forward extension.
        """
        if v in _TARGET_FIELD_VOCABULARY:
            return v
        # Allow any dotted path whose top-level segment is in the vocabulary.
        head = v.split(".", 1)[0]
        if head in _TARGET_FIELD_VOCABULARY:
            return v
        raise ValueError(
            f"target_field={v!r} is not a recognized StrategySpec or CodeModule "
            f"field. Allowed root vocabulary: {sorted(_TARGET_FIELD_VOCABULARY)}"
        )


class CriticVerdict(BaseContract):
    """Phase 48 § Decision 1 — structured Critic output for refinement loops.

    9 fields total. Strict superset of Phase 37 Critique. Constructing this
    with an `is_stalling` field is REJECTED (extra='forbid' on BaseContract) —
    convergence detection is orchestration policy, not Critic cognition
    (CONTEXT.md § Decision 7 + § Anti-Patterns).
    """

    verdict: Literal["ACCEPT", "REFINE", "REJECT"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    refinement_targets: list[RefinementTarget]
    failure_modes: list[str]  # canonical IDs
    rationale: str
    loaded_skills: list[str]
    source_critic_verdict_id: Optional[str] = None
    registry_snapshot_hash: str
    schema_version: int = 1


class RefinementContextEnvelope(BaseContract):
    """Phase 48 § Decision 5 — typed feedback packet routed back into next iteration.

    Carries prior-iteration artifact IDs + RefinementTargets + identity_score +
    registry_snapshot_hash. Strategy / Code Agent prompts receive THIS envelope
    (never prose) for the next regeneration pass.
    """

    iteration: int = Field(..., ge=0)
    prior_strategy_spec_id: str
    prior_code_module_id: str
    prior_build_report_id: str
    prior_backtest_result_id: str
    critic_verdict_id: str
    refinement_targets: list[RefinementTarget]
    identity_score: float = Field(..., ge=0.0, le=1.0)
    registry_snapshot_hash: str
    schema_version: int = 1


class RefinementLoopState(BaseContract):
    """Phase 48 § Decision 3 — canonical orchestration state.

    Owned exclusively by orchestrator. Persisted to `refinement_loops` Mongo
    collection. Acts as trajectory index — does NOT duplicate per-iteration
    artifact bodies (those persist append-only to their own collections;
    iteration_artifact_ids[] holds the cross-collection join keys).
    """

    loop_id: str
    root_hypothesis_id: str
    strategy_family: str
    loop_registry_snapshot_hash: str
    iteration: int = Field(..., ge=0)
    max_iterations: int = 3
    iteration_artifact_ids: list[dict[str, Any]] = Field(default_factory=list)
    strategy_version: str
    code_version: str
    critic_history: list[str] = Field(default_factory=list)
    veto_history: list[dict[str, Any]] = Field(default_factory=list)
    identity_scores: list[float] = Field(default_factory=list)
    refinement_delta_history: list[str] = Field(default_factory=list)
    budget_snapshot: dict[str, Any] = Field(default_factory=dict)
    termination_reason: Optional[str] = None
    started_at: datetime
    updated_at: datetime
    # Phase 48 Plan 48-03 — anchored-identity field per CONTEXT § Decision 10.
    # main_loop (Plan 08b) writes the iter-0 StrategySpec ID into this field
    # after iteration 0 completes; subsequent iterations look it up here when
    # calling identity_scorer.compute_score. Identity ALWAYS anchors to iter 0
    # (NEVER iter N-1) so creeping drift is impossible.
    spec_iter0_id: Optional[str] = None
    schema_version: int = 1


class DeterministicAcceptanceResult(BaseContract):
    """Phase 48 § Decision 8 — deterministic acceptance-floor outcome.

    Emitted by orchestrator BEFORE Critic LLM executes. Layering:
        Phase 45 validity floor  → "Is the backtest valid?"
        Phase 48 acceptance floor → "Is this strategy worth refining further / accepting?"
        Critic verdict            → "Is this strategy strategically promising?"
    """

    passed: bool
    failed_constraints: list[str] = Field(default_factory=list)
    metrics_snapshot: dict[str, Any] = Field(default_factory=dict)
    classification: AcceptanceClassification
    schema_version: int = 1


class ExecutionCost(BaseContract):
    """Phase 48 § Decision 14 — per-stage cost record.

    Two categories tracked independently:
    - LLM: cognition cost (tokens + USD).
    - INFRASTRUCTURE: compute cost (Backtester wall-time dominates LLM tokens
      for slow VM102 calls; tracked separately to avoid distortion).
    """

    tokens_in: int = Field(..., ge=0)
    tokens_out: int = Field(..., ge=0)
    usd_cost: float = Field(..., ge=0.0)
    wall_time_ms: int = Field(..., ge=0)
    category: Literal["LLM", "INFRASTRUCTURE"]
    schema_version: int = 1


class RefinementOutcome(BaseContract):
    """Phase 48 § Decision 2 — terminal result of `run_refinement_loop(...)`.

    Carries the loop's termination reason + which strategy (if any) was
    promoted / archived + the aggregate cost record. Single public surface
    returned by orchestrator entry point.
    """

    loop_id: str
    termination_reason: TerminationReason
    accepted_strategy_id: Optional[str] = None
    rejected_strategy_id: Optional[str] = None
    final_iteration: int = Field(..., ge=0)
    total_cost: ExecutionCost
    schema_version: int = 1


# =============================================================================
# Phase 47.3 re-exports (preserved from earlier code)
# =============================================================================

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
