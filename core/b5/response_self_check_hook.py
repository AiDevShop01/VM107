"""Phase 89 Plan 01 — B5 response self-check hook logic.

This module contains the pure logic called by the extension hook
(extensions/python/response_self_check/_10_b5_self_check.py).
Extracted as a separate module so tests can import and call run_b5_hook()
directly without the full Extension framework.

Decision flow:
  accept  → set confidence_self_report + b5_result; continue
  refine  → if loops < max_loops: inject refinement context + re-run
  refine (exhausted) → degrade
  reject  → degrade immediately (no refinement)

Pitfall 1 cost guard:
  If b5_utility_model_spend > cost_budget.utility_model_usd, skip refinement
  and degrade immediately.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from core.b5.rubric_loader import load_rubric
from core.b5.rubric_scorer import score_answer

if TYPE_CHECKING:
    pass  # Agent type is duck-typed (MagicMock in tests, Agent in prod)

logger = logging.getLogger(__name__)


def run_b5_hook(agent: Any) -> None:
    """Run the B5 self-evaluation loop for the given agent.

    Modifies agent in-place:
      - agent.set_data("confidence_self_report", score_total)
      - agent.set_data("b5_result", result_dict)
      - agent.set_data("b5_degraded", True) on reject/second-fail
      - agent.last_response replaced with graceful_degradation_text on degrade

    Safe to call in tests via direct import — no Extension framework required.

    Args:
        agent: The agent instance (duck-typed; provides get_data/set_data/last_response).
    """
    profile: dict = getattr(agent, "profile", {}) or {}

    # Profile guard — only fire for b5_self_eval=True profiles
    if not profile.get("b5_self_eval"):
        return

    rubric_id: str | None = profile.get("b5_rubric_id")
    if not rubric_id:
        logger.warning(
            "b5_hook_missing_rubric_id",
            extra={"profile_id": profile.get("id", "unknown")},
        )
        return

    # Load rubric (fail-fast if missing from registry)
    try:
        rubric = load_rubric(rubric_id)
    except RuntimeError as exc:
        logger.error(
            "b5_hook_rubric_load_failed",
            extra={"rubric_id": rubric_id, "error": str(exc)},
        )
        return  # Can't evaluate — continue without B5 (degrades gracefully)

    # Cost guard (Pitfall 1) — check utility-model spend before scoring
    cost_budget: dict = profile.get("cost_budget_per_invocation", {})
    util_budget: float = cost_budget.get("utility_model_usd", 0.20)
    util_spent: float = agent.get_data("b5_utility_model_spend", 0.0) or 0.0

    # Get current agent response text
    answer: str = agent.last_response or ""

    # Get prompt context (for range-scope enforcement, Decision 5)
    prompt_context: dict = agent.get_data("prompt_context") or {}

    # Score the answer
    result = score_answer(answer=answer, rubric=rubric, prompt_context=prompt_context)

    recommendation: str = result["recommendation"]
    total: float = result["total"]

    # Always record the score (even on reject/degrade)
    agent.set_data("confidence_self_report", total)
    agent.set_data("b5_result", result)

    if recommendation == "accept":
        # Happy path — response is good
        logger.debug(
            "b5_accept",
            extra={"total": total, "profile_id": profile.get("id")},
        )
        return

    refinement_loops: int = agent.get_data("b5_refinement_loops", 0) or 0
    max_loops: int = rubric.get("refinement", {}).get("max_loops", 1)

    if recommendation == "refine" and refinement_loops < max_loops:
        # Pitfall 1 cost guard — skip refinement if over budget
        if util_spent >= util_budget:
            logger.warning(
                "b5_refine_skipped_cost_guard",
                extra={
                    "util_spent": util_spent,
                    "util_budget": util_budget,
                    "total": total,
                },
            )
            _degrade(agent, rubric, total)
            return

        # Inject refinement context into conversation history and re-run
        agent.set_data("b5_refinement_loops", refinement_loops + 1)
        refinement_context: str | None = result.get("refinement_context")
        if refinement_context:
            # Inject into conversation as system/user guidance
            _inject_refinement_context(agent, refinement_context)
        logger.info(
            "b5_refine",
            extra={"loop": refinement_loops + 1, "total": total},
        )
        # The caller (extension hook) re-runs the monologue after this returns.
        # We set the loop counter; the extension checks it on next invocation.
        return

    # refine exhausted OR reject → degrade
    _degrade(agent, rubric, total)


def _degrade(agent: Any, rubric: dict, total: float) -> None:
    """Replace agent response with graceful degradation text and mark degraded."""
    degradation_text: str = rubric.get(
        "graceful_degradation_text",
        "I'm not confident enough to answer this — please try a narrower question.",
    )
    agent.last_response = degradation_text
    agent.set_data("b5_degraded", True)
    # Ensure confidence_self_report is set (already set before _degrade is called)
    logger.warning(
        "b5_degrade",
        extra={
            "total": total,
            "profile_id": getattr(agent, "profile", {}).get("id", "unknown"),
        },
    )


def _inject_refinement_context(agent: Any, refinement_context: str) -> None:
    """Inject B5 refinement guidance into the agent conversation history.

    In production: appends a synthetic system message to the agent's message
    loop so the next LLM call sees the refinement guidance.
    In tests: the MagicMock absorbs the call via set_data.
    """
    # Store refinement context in agent data for the next loop iteration
    agent.set_data("b5_refinement_context", refinement_context)
    # Production agents read b5_refinement_context in message_loop_prompts_before
    # to inject into the next LLM call. This is the agreed injection point.
    logger.debug("b5_refinement_context_injected", extra={"context_len": len(refinement_context)})
