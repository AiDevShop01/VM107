"""Phase 89 Plan 01 — B5 rubric scorer.

Scores an investigator answer against a rubric using the Phase 43.1
utility-model path (cheap fast model per Decision 6 / Pitfall 1).

Special-case enforcement:
  - Decision 9 (word cap): confidence_calibrated_and_concise → 0.0 if
    word_count > hard_cap; multiplied by 0.5 if between target and hard_cap.
  - Decision 5 (range scope): claims_within_cited_evidence → 0.0 if
    prompt_context.zoom_range is set and answer references dates outside the range.

Routing:
  - Per rubric.utility_model_routing.use_phase_43_1: True → calls
    _call_utility_model_for_check() which wraps the Phase 43.1 utility model.
  - All utility model calls go through _call_utility_model_for_check() —
    test mocks patch ONLY that function (not the chat model path).

Public API:
  score_answer(answer, rubric, prompt_context) → ScorerResult dict

ScorerResult fields:
  total             — weighted sum (float 0.0–1.0)
  recommendation    — "accept" | "refine" | "reject"
  per_check         — {check_id: float} scores (after special-case overrides)
  refinement_context — str | None — guidance for the LLM on which checks failed
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date patterns for range-scope enforcement (Decision 5)
# ---------------------------------------------------------------------------

# Matches common date formats in LLM answers:
#   YYYY, YYYY-MM, YYYY-MM-DD, "YYYYs", e.g. "2008", "2008-09", "2008-09-15", "2008s"
_YEAR_PATTERN = re.compile(
    r"\b(1[89]\d{2}|20[012]\d)(?:-\d{1,2})?(?:-\d{1,2})?\b"
)


def _extract_years_from_text(text: str) -> list[int]:
    """Extract years mentioned in text (YYYY or YYYY-MM or YYYY-MM-DD or YYYYs)."""
    return [int(m.group(1)) for m in _YEAR_PATTERN.finditer(text)]


def _answer_references_outside_range(answer: str, start_ts: str, end_ts: str) -> bool:
    """Return True if the answer mentions years outside [start_year, end_year].

    Parses the 4-digit year from start_ts and end_ts ISO strings.
    If the answer mentions ANY year strictly outside that range, returns True.

    Conservative: "2008" in an answer scoped to 2023 triggers this.
    """
    try:
        start_year = int(start_ts[:4])
        end_year = int(end_ts[:4])
    except (ValueError, IndexError, TypeError):
        # Unparseable timestamp — skip range enforcement to avoid false positives
        return False

    mentioned_years = _extract_years_from_text(answer)
    for y in mentioned_years:
        if y < start_year or y > end_year:
            return True
    return False


# ---------------------------------------------------------------------------
# Utility model call stub — tests patch this
# ---------------------------------------------------------------------------


def _call_utility_model_for_check(
    check_id: str,
    *,
    check_description: str,
    answer: str,
    prompt_context: dict,
) -> float:
    """Call the Phase 43.1 utility model to score one rubric check.

    Returns a float in [0.0, 1.0] representing how well the answer satisfies
    the check description.

    In production: calls the Phase 43.1 utility-model routing client
    (cheap/fast model alias per Decision 6 + Pitfall 1 cost guard).

    In tests: patched via:
        patch("core.b5.rubric_scorer._call_utility_model_for_check",
              side_effect=lambda check_id, **_kw: canned_scores[check_id])

    Phase 43.1 integration note:
        The utility model is called with a minimal prompt asking the model
        to rate [0.0-1.0] whether the answer satisfies the check description.
        We use the `util_model_call_before/after` extension slots if available,
        or fall back to a direct utility model client call.
    """
    try:
        from helpers.call_llm import call_utility_model
        prompt = (
            f"Rate 0.0 to 1.0 (one decimal) how well this answer satisfies:\n"
            f"CHECK: {check_description}\n\n"
            f"ANSWER:\n{answer}\n\n"
            f"Reply with ONLY a float between 0.0 and 1.0, nothing else."
        )
        raw = call_utility_model(prompt, context=prompt_context)
        # Parse the float from the model response
        score = float(raw.strip().split()[0])
        return max(0.0, min(1.0, score))
    except Exception as exc:
        logger.warning(
            "b5_utility_model_check_failed",
            extra={"check_id": check_id, "error": str(exc)},
        )
        # Fail-open at check level: return 0.5 (ambiguous) so one failed check
        # doesn't immediately reject; Pitfall 1 cost guard may apply at hook level.
        return 0.5


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_answer(
    answer: str,
    rubric: dict,
    prompt_context: dict | None = None,
) -> dict[str, Any]:
    """Score an answer against a rubric and return a ScorerResult dict.

    Args:
        answer: The LLM-generated investigator answer text.
        rubric: The rubric dict from load_rubric() or _canned_rubric() in tests.
        prompt_context: Optional dict with zoom_range={start_ts, end_ts} for
                        Decision 5 range-scope enforcement.

    Returns:
        {
            "total": float,               # weighted sum of per-check scores
            "recommendation": str,        # "accept" | "refine" | "reject"
            "per_check": dict[str, float],
            "refinement_context": str | None,  # non-None on "refine"
        }
    """
    if prompt_context is None:
        prompt_context = {}

    checks: list[dict] = rubric.get("checks", [])
    threshold: dict = rubric.get("threshold", {})
    word_cap_config: dict = rubric.get("word_cap", {})

    accept_threshold: float = threshold.get("accept", 0.75)
    reject_threshold: float = threshold.get("reject_below", 0.40)

    hard_cap: int = word_cap_config.get("hard_cap", 400)
    target_cap: int = word_cap_config.get("target", 250)
    word_count: int = len(answer.split())

    # Pre-compute range-scope flag (Decision 5)
    zoom_range = prompt_context.get("zoom_range") or {}
    start_ts: str | None = zoom_range.get("start_ts")
    end_ts: str | None = zoom_range.get("end_ts")
    out_of_range: bool = False
    if start_ts and end_ts:
        out_of_range = _answer_references_outside_range(answer, start_ts, end_ts)

    per_check: dict[str, float] = {}
    failing_checks: list[str] = []

    for check in checks:
        check_id: str = check["id"]
        weight: float = check["weight"]
        description: str = check.get("description", "")

        # --- Special-case: confidence_calibrated_and_concise (Decision 9) ---
        if check_id == "confidence_calibrated_and_concise":
            if word_count > hard_cap:
                # Hard cap exceeded — force to 0.0 regardless of LLM score
                per_check[check_id] = 0.0
                failing_checks.append(
                    f"{check_id} (word count {word_count} exceeds hard cap {hard_cap})"
                )
                continue
            else:
                # LLM scores; if between target and hard_cap, multiply by 0.5
                raw_score = _call_utility_model_for_check(
                    check_id,
                    check_description=description,
                    answer=answer,
                    prompt_context=prompt_context,
                )
                if word_count > target_cap:
                    raw_score = raw_score * 0.5
                per_check[check_id] = max(0.0, min(1.0, raw_score))

        # --- Special-case: claims_within_cited_evidence (Decision 5) ---
        elif check_id == "claims_within_cited_evidence" and out_of_range:
            per_check[check_id] = 0.0
            failing_checks.append(
                f"{check_id} (answer references dates outside "
                f"[{start_ts}, {end_ts}])"
            )
            continue

        else:
            raw_score = _call_utility_model_for_check(
                check_id,
                check_description=description,
                answer=answer,
                prompt_context=prompt_context,
            )
            per_check[check_id] = max(0.0, min(1.0, raw_score))

        if per_check[check_id] < 0.60:
            failing_checks.append(f"{check_id} (score={per_check[check_id]:.2f})")

    # Weighted sum
    total: float = sum(
        per_check.get(c["id"], 0.0) * c["weight"] for c in checks
    )
    total = max(0.0, min(1.0, total))

    # Route per threshold
    if total >= accept_threshold:
        recommendation = "accept"
        refinement_context = None
    elif total >= reject_threshold:
        recommendation = "refine"
        # Build refinement context for the LLM
        if failing_checks:
            failing_str = "; ".join(failing_checks)
            refinement_context = (
                f"Your prior answer scored low on: {failing_str}. "
                f"Please re-answer with: cite specific evidence sources via [ref:...] grammar, "
                f"stay within the requested time range, use correlation language (not causation), "
                f"and keep the answer under {hard_cap} words."
            )
        else:
            refinement_context = (
                "Your prior answer did not meet quality standards. "
                "Please provide more specific citations and acknowledge uncertainty."
            )
    else:
        recommendation = "reject"
        refinement_context = None  # No refinement on reject — degrade immediately

    logger.debug(
        "b5_score_complete",
        extra={
            "total": total,
            "recommendation": recommendation,
            "word_count": word_count,
            "failing_checks": failing_checks,
        },
    )

    return {
        "total": total,
        "recommendation": recommendation,
        "per_check": per_check,
        "refinement_context": refinement_context,
    }
