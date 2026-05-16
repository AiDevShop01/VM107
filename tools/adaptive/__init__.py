"""Phase 62-03 — Adaptive tools surface.

Three scope-aware HTTP client tools that read frozen adaptive artifacts
from VM100 internal endpoints.

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.

CTX-DEC-14: Tools prune themselves if their signal_category is NOT in
    the caller's adaptive_signal_categories frozenset. The orchestrator
    ALSO prunes BEFORE planning — this is defense-in-depth only.
CTX-DEC-17: All returned rows carry truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — returned rows are NOT surfaced to apply UI.
"""

from tools.adaptive.get_drift_report import get_drift_report
from tools.adaptive.get_counterfactual_scenario_stats import get_counterfactual_scenario_stats
from tools.adaptive.get_behavioral_drift_summary import get_behavioral_drift_summary

__all__ = [
    "get_drift_report",
    "get_counterfactual_scenario_stats",
    "get_behavioral_drift_summary",
]
