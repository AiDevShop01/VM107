"""Phase 91 Plan 6 — vm107.macro_review_agent agent package.

Synchronous agent that reviews high-severity alert candidates (liquidity
critical, regime_change) and emits follow-up alert_candidate envelopes
when findings warrant. NEVER targets itself — denied_dispatch_targets
list in profile.yaml enforces self-loop prevention at the agent contract
layer (independent of VM100's loop_safety_guard depth check).
"""
from .agent import MacroReviewAgent, review_alert  # noqa: F401
