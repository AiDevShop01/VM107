"""
Contract validation layer for agent communication.

Public API exports for the contracts package.
"""
from core.contracts.base import BaseContract
from core.contracts.registry import SCHEMA_REGISTRY, validate_message
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

__all__ = [
    "BaseContract",
    "Hypothesis",
    "StrategySpec",
    "CodeModule",
    "BacktestMetrics",
    "BacktestResult",
    "Critique",
    "A2AMessage",
    "MessageType",
    "Priority",
    "SCHEMA_REGISTRY",
    "validate_message",
]
