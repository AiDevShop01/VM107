"""Phase 87 Plan 06 — macro_regime_analyst (Wave 3).

Event-driven analyst that wakes on Phase 83 econ_release events. Classifies
the current macro regime per LOCK-10 approved 27-entry threshold table
(``regime_threshold_table.json``), retrieves top-3 historical analogues via
Phase 86 ``/event-study``, persists a ``macro_regime_classification`` envelope
within 60s per REQ-87-3.

Wave 3 ships with the BeliefStore client STUBBED. Plan 87-09 (Wave 5) swaps
in the real B9 BeliefStore without changing the agent's call site.

Public surface is exposed lazily — Task 1 lands the classifier + analogue
client; Task 2 lands the agent + narration skill. Imports here use
try/except so partial-state checkouts (Task 1 before Task 2) still load.
"""
from .historical_analogue_client import EventStudyAnalogueClient, HistoricalAnalogue
from .skill_regime_classifier import classify_regime, transition_probability_v1

__all__ = [
    "EventStudyAnalogueClient",
    "HistoricalAnalogue",
    "classify_regime",
    "transition_probability_v1",
]

try:  # Task 2 — agent + narration skill
    from .agent import MacroRegimeAnalyst, RegimeClassificationResult  # noqa: F401
    from .skill_regime_narration import (  # noqa: F401
        NarrationFailedAfterRetry,
        RegimeNarrationSkill,
    )

    __all__ += [
        "MacroRegimeAnalyst",
        "RegimeClassificationResult",
        "RegimeNarrationSkill",
        "NarrationFailedAfterRetry",
    ]
except ImportError:  # pragma: no cover — partial-state during Task 1
    pass
