"""Phase 47.3 — Decision Framework V1.

Pure Python rules engine. LLM never decides scoring or category status.

Public surface (populated incrementally across Plans 03/04/05):
- ``EvaluationContext`` — frozen Pydantic input passed to every category evaluator
  (Plan 03 — context module).
- ``derive_recommendation_band`` — score → band mapping (Plan 03 — bands module).
- ``Framework`` + ``PythonEngineResult`` — orchestrator + result dataclass
  (Plan 03 Task 2 — framework module).
- ``register_override`` + ``CategoryWeight`` — strategy-override decorator
  (Plan 03 Task 2 — overrides module).
- ``register_hard_reject`` — hard-reject predicate decorator
  (Plan 03 Task 2 — hard_rejects module).

The full re-export wiring is added by Plan 03 Task 2 once all modules ship.
"""

from core.agents.decision_framework.bands import derive_recommendation_band
from core.agents.decision_framework.context import EvaluationContext

__all__ = [
    "EvaluationContext",
    "derive_recommendation_band",
]
