"""Phase 47.3 — Decision Framework V1.

Pure Python rules engine. LLM never decides scoring or category status.

Public surface:
- ``Framework`` + ``PythonEngineResult`` — orchestrator + result dataclass.
- ``EvaluationContext`` — frozen Pydantic input passed to every category evaluator.
- ``derive_recommendation_band`` — pure score → band mapping.
- ``register_override`` + ``CategoryWeight`` — strategy-override decorator + result type.
- ``register_hard_reject`` — hard-reject predicate decorator.
"""

from core.agents.decision_framework.bands import derive_recommendation_band
from core.agents.decision_framework.context import EvaluationContext
from core.agents.decision_framework.framework import (
    CATEGORY_ORDER,
    Framework,
    PythonEngineResult,
)
from core.agents.decision_framework.hard_rejects import register_hard_reject
from core.agents.decision_framework.overrides import (
    CategoryWeight,
    register_override,
)

__all__ = [
    "Framework",
    "PythonEngineResult",
    "CATEGORY_ORDER",
    "EvaluationContext",
    "derive_recommendation_band",
    "register_override",
    "CategoryWeight",
    "register_hard_reject",
]
