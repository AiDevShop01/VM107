"""Phase 89 Plan 01 — B5 response self-check extension hook.

Extension slot: response_self_check (fires after LLM response stream ends,
BEFORE reasoning_stream_end/_20_persist_reasoning_artifact.py).

Ordering: _10_*.py fires first in this slot (slot prefix 10).

The Phase 36 AgentRunner discovers this extension via the standard extension
discovery mechanism (helpers/extension.py: _get_extension_classes scans all
extensions/python/ subdirectories). No manual registration needed.

Profile guard: only fires when agent.profile.get('b5_self_eval') is True.
This prevents any overhead on non-investigator profiles.

Refinement loop guard: the extension increments b5_refinement_loops on refine.
The AgentRunner re-runs the monologue on refine IF b5_refinement_loops was
incremented (it reads the data slot to detect the signal).

After this extension fires and sets confidence_self_report, the
reasoning_stream_end/_20_persist_reasoning_artifact.py reads it via:
    agent.get_data("confidence_self_report")
and writes it to the B1 artifact row (Pitfall 8 wiring closed in Phase 89).

See core/b5/response_self_check_hook.py for the pure-logic layer (testable
without the full Extension framework).
"""
from __future__ import annotations

import logging

from helpers.extension import Extension
from core.b5.response_self_check_hook import run_b5_hook

logger = logging.getLogger(__name__)


class B5SelfCheckExtension(Extension):
    """B5 self-evaluation extension — fires in response_self_check slot.

    Calls run_b5_hook(agent) which handles:
      - accept → confidence_self_report set, b5_result stored
      - refine → loop counter incremented, refinement context injected
      - reject / second-fail → response replaced with graceful degradation text

    This extension does NOT crash the agent loop on any error (B5 is
    quality assurance, not a hard gate for loop continuity).
    """

    async def execute(self, **kwargs):
        agent = kwargs.get("agent") or self.agent
        if not agent:
            return

        profile = getattr(agent, "profile", {}) or {}
        if not profile.get("b5_self_eval"):
            # Not a B5-enabled profile — skip silently
            return

        # loop_data is passed by agent.py's response_self_check call site so that
        # run_b5_hook can read/write the current response text via
        # loop_data.params_temporary["current_agent_response"].
        loop_data = kwargs.get("loop_data")

        try:
            run_b5_hook(agent, loop_data=loop_data)
        except Exception as exc:
            # B5 is observability / quality gate — it must NOT crash the agent loop.
            # Log at ERROR so monitoring detects B5 outages without breaking emission.
            logger.error(
                f"b5_self_check_failed profile={profile.get('id', 'unknown')} error={type(exc).__name__}: {exc}",
                exc_info=True,
                extra={
                    "event": "b5_self_check_failed",
                    "profile_id": profile.get("id", "unknown"),
                    "error": str(exc),
                },
            )
