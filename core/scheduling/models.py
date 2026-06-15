"""
Pydantic models for Goal/Task scheduling system.

Provides GoalModel, TaskModel with full lifecycle validation,
and CreateRequest schemas for input validation.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

from core.scheduling.enums import GoalStatus, TaskStatus, GoalType, Priority


class GoalModel(BaseModel):
    """
    Goal entity model with 8-state lifecycle.

    Goals decompose into Task DAGs. Lifecycle: draft → proposed → approved → active
    → paused → completed | failed | cancelled. Shortcuts allowed for maintenance/learning.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    goal_id: str = Field(..., description="Unique goal identifier")
    title: str = Field(..., min_length=3, max_length=200, description="Goal title")
    description: str = Field(..., description="Goal description")

    # Classification
    goal_type: GoalType = Field(..., description="Goal type (maintenance/learning/research/execution/system)")
    status: GoalStatus = Field(..., description="Current lifecycle status")
    priority: Priority = Field(..., description="Execution priority (P1-P4)")

    # Metadata grouping
    objective_label: Optional[str] = Field(None, description="Metadata grouping label (e.g., 'market_intelligence')")
    decomposition_template: Optional[str] = Field(None, description="Template name for task decomposition")

    # Governance
    created_by: str = Field(..., description="Creator ID (user or agent)")
    governance_tier: str = Field(..., description="Governance tier (auto/approval/human-only)")

    # Budget constraints
    budget_max_cost_usd: Optional[float] = Field(None, ge=0, description="Maximum cost in USD")
    budget_max_tokens: Optional[int] = Field(None, ge=0, description="Maximum token count")

    # Task DAG
    task_ids: list[str] = Field(default_factory=list, description="List of task IDs in this goal's DAG")

    # Phase 85.1: structured payload carrying domain-specific event data
    # (e.g. macro release: indicator_id, actual, consensus). Read by the
    # dispatcher when building per-profile agent prompt envelopes.
    payload: Optional[dict] = Field(None, description="Domain-specific structured payload (e.g. macro release event fields)")

    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    # Schema versioning
    schema_version: int = Field(1, description="Schema version for evolution")


class TaskModel(BaseModel):
    """
    Task entity model with 7-state lifecycle.

    Tasks are nodes in a Goal's DAG. Lifecycle: pending → blocked → queued → running
    → completed | failed | cancelled. blocked_by tracks dependencies.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    task_id: str = Field(..., description="Unique task identifier")
    goal_id: str = Field(..., description="Parent goal ID")
    task_type: str = Field(..., description="Task type (analysis/execution/validation/etc)")

    # Lifecycle
    status: TaskStatus = Field(..., description="Current lifecycle status")
    priority: Priority = Field(..., description="Execution priority (P1-P4)")

    # Dependencies
    dependencies: list[str] = Field(default_factory=list, description="Task IDs this task depends on")
    blocked_by: list[str] = Field(default_factory=list, description="Task IDs blocking this task")

    # Pre-emption support
    preemptible: bool = Field(False, description="Whether task can be pre-empted")
    checkpoint_interval_seconds: Optional[int] = Field(None, ge=1, description="Checkpoint interval for pre-emption")

    # Retry tracking
    retry_count: int = Field(0, ge=0, description="Number of retries attempted")
    max_retries: int = Field(3, ge=0, description="Maximum retry attempts")

    # Cost estimation
    estimated_cost_usd: Optional[float] = Field(None, ge=0, description="Estimated cost in USD")
    deadline: Optional[float] = Field(None, description="Unix timestamp deadline")

    # Execution tracking
    agent_name: Optional[str] = Field(None, description="Agent assigned to this task")
    queued_at: Optional[datetime] = Field(None, description="When task entered queue")
    started_at: Optional[datetime] = Field(None, description="When task started running")
    completed_at: Optional[datetime] = Field(None, description="When task completed")

    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    # Schema versioning
    schema_version: int = Field(1, description="Schema version for evolution")


class GoalCreateRequest(BaseModel):
    """Input validation for goal creation."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=3, max_length=200)
    description: str
    goal_type: GoalType
    priority: Priority
    created_by: str
    objective_label: Optional[str] = None
    decomposition_template: Optional[str] = None
    budget_max_cost_usd: Optional[float] = Field(None, ge=0)
    budget_max_tokens: Optional[int] = Field(None, ge=0)


class TaskCreateRequest(BaseModel):
    """Input validation for task creation."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str
    task_type: str
    priority: Priority
    dependencies: list[str] = Field(default_factory=list)
    preemptible: bool = False
    checkpoint_interval_seconds: Optional[int] = Field(None, ge=1)
    estimated_cost_usd: Optional[float] = Field(None, ge=0)
    deadline: Optional[float] = None
