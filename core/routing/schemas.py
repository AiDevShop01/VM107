"""
Pydantic v2 schemas for the LLM Model Router.

These schemas form the contract boundary between the routing layer and all
consumers (extensions, tests, observability). Shapes are locked per CONTEXT.md
and must not be changed without a Phase 43 context revision.

Contract shapes (LOCKED):
- RouterContext: task/goal/agent context at decision time
- RoutingDecision: primary + fallback chain with structured reason list
- CostRecord: per-call token+cost+latency capture for Redis/MongoDB
- AlertEvent: multi-scope budget alert with sink tracking
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RouterContext(BaseModel):
    """
    Immutable context bundle passed to ModelRouter.decide() on every LLM call.

    Populated by AgentRunner.start_task() via agent.set_data("router_context", {...})
    and read by the before_main_llm_call extension.

    Fields:
        task_id: Unique task identifier from TaskModel
        goal_id: Parent goal identifier from GoalModel
        agent_id: Agent name (e.g. "agent_zero")
        task_type: Free-form type string from TaskModel.task_type (Phase 42 verbatim)
        priority: Task priority level
        latency_sla_ms: Maximum acceptable response latency in milliseconds
        brain_context: Brain state snapshot at decision time (mode, confidence, resource_policy)
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    goal_id: str
    agent_id: str
    task_type: str
    priority: Literal["P1", "P2", "P3", "P4"]
    latency_sla_ms: int = Field(default=30000, ge=0)
    brain_context: dict = Field(default_factory=dict)
    # Phase 43.1: routing path — "chat" for brain/thinking calls, "utility" for agent hands calls.
    # Default "chat" preserves Phase 43 semantics — NO behavior change on existing paths.
    path: Literal["chat", "utility"] = "chat"


class RoutingDecision(BaseModel):
    """
    Output of ModelRouter.decide() — the primary model selection + fallback chain.

    Returned to the before_main_llm_call extension which stores it in
    loop_data.params_temporary["router_decision"] for the chat_model_call_before
    extension to apply via call_data["model"] replacement.

    Fields:
        task_id: Task this decision was made for
        goal_id: Parent goal
        agent_id: Agent name
        task_type: Task type used for affinity lookup
        primary: Selected primary model identifier
        fallback: Ordered list of fallback model identifiers (always ends with local)
        reason: Structured reason list (e.g. ["mode=exploration", "budget_ok", "affinity=analysis"])
        decision_time_ms: Time taken to compute decision in milliseconds
        selected_model: Alias for primary (convenience field)
        peak: Whether decision was made during peak hours
        mode: Brain mode at decision time
        force_local: Whether budget breach forced local-only selection
    """

    task_id: str
    goal_id: str
    agent_id: str
    task_type: str
    primary: str
    fallback: list[str] = Field(default_factory=list)
    reason: list[str] = Field(default_factory=list)
    decision_time_ms: float
    selected_model: str
    peak: bool = False
    mode: str = "exploration"
    force_local: bool = False
    # Phase 43.1: routing path — mirrors RouterContext.path for log correlation.
    # Default "chat" preserves Phase 43 semantics.
    path: Literal["chat", "utility"] = "chat"
    # Phase 43.2: failover chain tracking (safe defaults for backward-compat with old docs).
    # chain_index=0 means primary succeeded; N means Nth fallback succeeded.
    # fallback_used is denormalized for fast Mongo queries ($eq True).
    # attempt_count=1 means no failover occurred.
    chain_index: int = 0
    fallback_used: bool = False
    attempt_count: int = 1


class CostRecord(BaseModel):
    """
    Per-call cost capture written after chat_model_call_after fires.

    Written to MongoDB agent_runs.task_results and used to update Redis
    aggregate keys (router:budget:goal:{goal_id}, router:budget:agent:{agent_type},
    router:budget:system).

    Fields:
        task_id: Task this call was part of
        model: Model identifier that handled the call
        tokens: Total token count (input + output, tiktoken estimate if unavailable)
        cost_usd: Estimated cost in USD
        latency_ms: Observed call latency in milliseconds
        goal_id: Parent goal for budget aggregation
        agent_id: Agent name for agent-type aggregation
    """

    task_id: str
    model: str
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    latency_ms: int = Field(ge=0)
    goal_id: str
    agent_id: str
    # Phase 43.1: routing path for cost-separation dashboard queries.
    # Default "chat" provides backward-compatibility for records written pre-43.1.
    path: Literal["chat", "utility"] = "chat"
    # Phase 43.2: failover chain tracking (same 3 fields as RoutingDecision, same defaults).
    # Allows MongoDB queries like {fallback_used: true} to surface failover events.
    # ONE CostRecord per call (the success only); per-attempt failures go to stdout events.
    chain_index: int = 0
    fallback_used: bool = False
    attempt_count: int = 1


class AlertEvent(BaseModel):
    """
    Budget alert event emitted by AlertPipeline when thresholds are crossed.

    Written to MongoDB router_alerts collection and fanned out to configured sinks.
    The sinks_fired field records which sinks successfully received the alert.

    Four sinks (LOCKED per CONTEXT.md):
    - stdout: Structured JSON log (always fires)
    - mongodb: router_alerts collection (always fires)
    - brain_signal: cost_pressure signal to SignalAccumulator (80% and 100% only)
    - external: External notification (Slack/Discord/email) (100% only)

    Fields:
        scope: Budget scope that triggered the alert
        threshold: Threshold that was crossed
        goal_id: Goal identifier (scope="goal" only)
        agent_type: Agent type (scope="agent_type" only)
        spent_usd: Amount spent at alert time
        max_usd: Budget ceiling
        pct: Fraction spent (0.0 to 1.5, allows over-budget reporting)
        sinks_fired: List of sink names that fired successfully
        created_at: Alert creation timestamp (UTC)
    """

    scope: Literal["goal", "agent_type", "system"]
    threshold: Literal["50pct", "80pct", "100pct"]
    goal_id: Optional[str] = None
    agent_type: Optional[str] = None
    spent_usd: float = Field(ge=0.0)
    max_usd: float = Field(ge=0.0)
    pct: float = Field(ge=0.0, le=1.5)
    sinks_fired: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
