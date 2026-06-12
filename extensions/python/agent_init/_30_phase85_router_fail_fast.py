"""Phase 85 agent_init extension — slot 30: router fail-fast for macro_* profiles.

Fires AFTER:
  slot 10 — _10_initial_message.py  (initial message injection)
  slot 15 — _15_load_profile_settings.py  (profile settings load)
  slot 20 — _20_router_deps.py  (Phase 43 graceful-degrade router wiring)

Behavior:
- If profile_id does NOT start with "vm107.macro_" → no-op (all other
  agents keep _20_router_deps.py's graceful degradation).
- If profile_id starts with "vm107.macro_" → calls assert_router_reachable(),
  which exits 1 if Redis is unreachable or REDIS_URL is unset.

REQ-85-7 / D2 lock: Phase 85 macro agents must fail-fast on Redis unavailability
rather than silently continuing with degraded routing. This is a NEW strictness
layer on top of the existing _20_ graceful-degrade — it does NOT change behavior
for any non-macro_* profile.

Extension idiom: synchronous execute() following the pattern in _20_router_deps.py.
"""
from __future__ import annotations

import logging

from helpers.extension import Extension

logger = logging.getLogger("phase85.router_fail_fast")


class Phase85RouterFailFast(Extension):
    def execute(self, **kwargs) -> None:
        if not self.agent:
            return

        profile_id: str = self.agent.get_data("profile_id") or ""

        # Only Phase 85 macro_* agents fail-fast on Redis unreachability.
        # All other agents keep existing graceful degradation from _20_router_deps.py.
        if not profile_id.startswith("vm107.macro_"):
            return

        logger.debug(
            f"Phase 85 fail-fast check for profile_id={profile_id!r}"
        )
        from agents._router_reachability import assert_router_reachable
        assert_router_reachable()
