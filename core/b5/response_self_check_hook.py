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

Utility model wiring (89.1-02 Round 2 fix):
  agent.call_utility_model(system, message) is an async method on Agent.
  run_b5_hook is synchronous (extension slot fires sync inside async context).
  _get_utility_model_fn() builds a synchronous wrapper that runs the async
  call in a thread pool with its own event loop — safe because we're inside
  an already-running event loop and cannot use asyncio.run() directly.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

from core.b5.rubric_loader import load_rubric
from core.b5.rubric_scorer import score_answer

if TYPE_CHECKING:
    pass  # Agent type is duck-typed (MagicMock in tests, Agent in prod)

logger = logging.getLogger(__name__)


def _get_utility_model_fn(agent: Any) -> Optional[Callable[[str], str]]:
    """Build a synchronous callable that calls agent.call_utility_model.

    agent.call_utility_model(system, message) is an async method. This hook
    is synchronous but runs inside an already-running asyncio event loop
    (Agent Zero's main loop). We cannot use asyncio.run() (RuntimeError:
    loop already running), so we spawn a ThreadPoolExecutor thread and run
    a fresh event loop there.

    Returns None if agent has no call_utility_model attribute (test stubs
    that don't need the real model, or agents without a utility model configured).
    In that case _call_utility_model_for_check returns 0.5 fail-open.

    Note: agents in tests that define a SYNCHRONOUS call_utility_model() are
    also supported — the wrapper detects whether the return value is a coroutine
    and handles both cases.
    """
    method = getattr(agent, "call_utility_model", None)
    if method is None:
        return None

    def _sync_call(prompt: str) -> str:
        # Build a minimal system + message pair for the check rating prompt.
        # The prompt already contains the full CHECK + ANSWER text.
        result = method(
            system="You are a precise evaluator. Rate answers on a 0.0-1.0 scale.",
            message=prompt,
        )
        # Handle both sync and async implementations
        if asyncio.iscoroutine(result):
            # Async — run in a new event loop in a thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, result)
                return future.result(timeout=30)
        # Sync — return directly (test stubs)
        return result

    return _sync_call


def run_b5_hook(agent: Any, loop_data: Any = None) -> None:
    """Run the B5 self-evaluation loop for the given agent.

    Modifies agent in-place:
      - agent.set_data("confidence_self_report", score_total)
      - agent.set_data("b5_result", result_dict)
      - agent.set_data("b5_degraded", True) on reject/second-fail
      - loop_data.params_temporary["current_agent_response"] replaced with
        graceful_degradation_text on degrade (agent.last_response doesn't exist on
        the Agent class — it lives on LoopData, and the current response text is
        stored in loop_data.params_temporary["current_agent_response"] by agent.py
        before calling the response_self_check extension slot).

    Safe to call in tests via direct import — no Extension framework required.

    IMPORTANT — agent.get_data() contract:
      Production Agent.get_data(self, field: str) accepts EXACTLY ONE argument
      (the key). It returns None when the key is absent — no default parameter.
      Always use: `agent.get_data("key") or default` NOT `agent.get_data("key", default)`.
      MagicMock absorbs extra args silently, so the wrong form passes all unit tests
      but raises TypeError in production (RCA 89.1-02: H4).

    Args:
        agent: The agent instance (duck-typed; provides get_data/set_data).
        loop_data: The LoopData instance (optional; used to read/write current
            response text via params_temporary["current_agent_response"]).
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
    util_spent: float = agent.get_data("b5_utility_model_spend") or 0.0

    # Get current agent response text.
    # Priority: loop_data.params_temporary["current_agent_response"] (set by agent.py
    # just before calling the response_self_check slot).
    # Fallback: loop_data.last_response (previous iteration, less accurate).
    # Final fallback: empty string (B5 will score low and degrade).
    answer: str = ""
    if loop_data is not None:
        answer = (
            loop_data.params_temporary.get("current_agent_response")
            or getattr(loop_data, "last_response", "")
            or ""
        )
    if not answer:
        # Legacy path for tests that don't pass loop_data
        answer = getattr(agent, "last_response", "") or ""

    # Get prompt context (for range-scope enforcement, Decision 5)
    prompt_context: dict = agent.get_data("prompt_context") or {}

    # Build utility model callable (89.1-02 Round 2 fix).
    # agent.call_utility_model is async; _get_utility_model_fn wraps it
    # as a synchronous callable so score_answer (sync) can invoke it.
    # Returns None if agent has no call_utility_model (tests that patch
    # _call_utility_model_for_check directly, or stub agents without model).
    utility_model_fn = _get_utility_model_fn(agent)

    # Score the answer
    result = score_answer(
        answer=answer,
        rubric=rubric,
        prompt_context=prompt_context,
        utility_model_fn=utility_model_fn,
    )

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

    refinement_loops: int = agent.get_data("b5_refinement_loops") or 0
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
            _degrade(agent, rubric, total, loop_data)
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
    _degrade(agent, rubric, total, loop_data)


def _degrade(agent: Any, rubric: dict, total: float, loop_data: Any = None) -> None:
    """Replace agent response with graceful degradation text and mark degraded."""
    degradation_text: str = rubric.get(
        "graceful_degradation_text",
        "I'm not confident enough to answer this — please try a narrower question.",
    )
    # Write degradation text to loop_data.params_temporary["current_agent_response"]
    # so agent.py picks it up when assembling the final answer.
    # agent.last_response does NOT exist on Agent — it lives on LoopData.
    if loop_data is not None:
        loop_data.params_temporary["current_agent_response"] = degradation_text
    else:
        # Legacy path for tests: fall back to attribute set (harmless if absent)
        try:
            agent.last_response = degradation_text
        except AttributeError:
            pass
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
