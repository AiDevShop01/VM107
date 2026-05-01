"""
core.routing — Phase 43 LLM Model Router package.

Deterministic, policy-driven model selection engine for VM107 agent calls.
All selection logic is implemented in pure Python with no LLM involvement.

Public API:
    ModelRouter   — 8-step routing pipeline (primary entry point)
    RouterContext — Immutable context passed to decide() on each call
    RoutingDecision — Primary + fallback chain returned by decide()
    CostRecord    — Per-call token/cost/latency capture
    AlertEvent    — Budget alert event with multi-sink fan-out

Sub-modules available for direct import:
    core.routing.affinity    — AffinityMap loader + lookup
    core.routing.budget_gate — BudgetGate Redis-backed enforcement
    core.routing.alert_pipeline — AlertPipeline multi-sink fan-out
    core.routing.peak_schedule  — PeakSchedule timezone-aware detection
    core.routing.scoring        — Score normalization pure functions
"""

from core.routing.router import ModelRouter
from core.routing.schemas import AlertEvent, CostRecord, RoutingDecision, RouterContext

__all__ = [
    "ModelRouter",
    "RouterContext",
    "RoutingDecision",
    "CostRecord",
    "AlertEvent",
]
