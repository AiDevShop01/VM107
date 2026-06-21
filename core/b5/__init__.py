"""Phase 89 Plan 01 — Brain B5 Response Self-Evaluation module.

Public API:
    load_rubric(rubric_id)   — load rubric YAML from registry via lookup_capability
    score_answer(answer, rubric, prompt_context) — score against rubric using utility model
    Recommendation           — enum: ACCEPT / REFINE / REJECT

Decision 6: per-profile rubric (investigator has its own; counterfactual is Wave 2).
Decision 5: range-scope enforcement in claims_within_cited_evidence check.
Decision 9: word-cap enforcement in confidence_calibrated_and_concise check.
Pitfall 1:  cost guard caps utility-model spend per invocation.
"""
from __future__ import annotations

from enum import Enum


class Recommendation(str, Enum):
    ACCEPT = "accept"
    REFINE = "refine"
    REJECT = "reject"


from core.b5.rubric_loader import load_rubric  # noqa: E402
from core.b5.rubric_scorer import score_answer  # noqa: E402

__all__ = ["Recommendation", "load_rubric", "score_answer"]
