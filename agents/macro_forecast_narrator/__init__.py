"""Phase 90 Plan 06 — macro_forecast_narrator agent package.

LLM narrative layer for the Phase 90 4-layer forecast intelligence engine.

Per LD-90-1 (LLMs MUST NOT be primary forecasters), this agent ONLY emits
``ExplanationResult`` — never ``ForecastResult``. It consumes a
ForecastResult-shaped dict from Plans 2-5 (statistical / ML / regime /
surprise) and produces a human-readable explanation citing Phase 71
evidence references.

Hard assertions enforced by ``macro_forecast_narrator_agent`` mirror
``registry/agent_profile/vm107.macro_forecast_narrator.yaml``:

  - narrator_no_value_prediction (regex ``\\b(will be|will reach|will
    print)\\b``) — match triggers ONE retry with corrective addendum.
  - narrative_cites_evidence (regex
    ``\\[ref:(episode|release):[A-Za-z0-9_-]+\\]``) — missing -> envelope
    flagged ``b5_self_eval_passed=False`` but still returned.
"""

from agents.macro_forecast_narrator.agent import macro_forecast_narrator_agent

__all__ = ["macro_forecast_narrator_agent"]
