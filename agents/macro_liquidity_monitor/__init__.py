"""Phase 91 Plan 3 Task 2 — vm107.macro_liquidity_monitor agent package.

NEW agent for Wave 3 — computes a global_liquidity_score from Phase 86
substrate (correlation breakdown signals + VM102 liquidity primitives) and
emits alert_candidate envelopes (alert_type='liquidity') via the shared
core/alerts/phase91_emit.py shim when the score crosses thresholds.

Status experimental: Phase 86 has not fully shipped the substrate this agent
relies on. ``compute_liquidity_score`` returns None for incomplete substrate
inputs and the agent silently emits nothing — matches profile.yaml status
"experimental".

Re-exports the package's public surface so callers can simply do::

    from agents.macro_liquidity_monitor import MacroLiquidityMonitor
"""
from .agent import MacroLiquidityMonitor, compute_liquidity_score

__all__ = ["MacroLiquidityMonitor", "compute_liquidity_score"]
