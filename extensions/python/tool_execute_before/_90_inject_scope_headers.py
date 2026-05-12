"""Phase 60.1 (G23) — auto-inject X-Agent-Scope headers into tool calls.

Fires before every tool execution via the tool_execute_before hook
(agent.py:931-936):
  call_extensions_async("tool_execute_before", self,
                         tool_args=tool_args or {}, tool_name=tool_name)

If the active agent has a prepared headers carrier (agent.data['_outbound_headers']),
this extension copies those headers into tool_args['headers'] so the tool's HTTP
client (if any) will attach them without manual wiring.

Design:
  - Late firing (_90_) — explicit headers set by LLM or earlier extensions win.
  - No-op when _outbound_headers is absent from agent.data.
  - No-op when tool_args is absent or None (tools that take no args).
  - Never raises — observability + graceful degradation.
  - Forward-compat with G11 cost tracking (which will land as
    tool_execute_after/_50_log_tool_http_cost.py using this same pattern).

CTX-§5 LOCKED: agents NEVER sign their own scope. This extension only
PROPAGATES headers the orchestrator already signed. Signing remains
centralized in ScopeDispatcher (populated by mentor_subordinate_invoker.py,
plans 60-13 + 60-16).
"""
from __future__ import annotations

import logging
from typing import Any

from helpers.extension import Extension

logger = logging.getLogger("fingpt.extensions.inject_scope_headers")


class _90_inject_scope_headers(Extension):
    """Auto-inject scope headers carried in agent.data into every tool call."""

    async def execute(self, tool_args: dict[str, Any] | None = None, tool_name: str = "", **kwargs: Any) -> None:
        # No agent — running outside any mentor pipeline; nothing to propagate.
        if not self.agent:
            return

        # No tool args (tool takes no arguments, or args were empty).
        if tool_args is None or not isinstance(tool_args, dict):
            return

        # Did the LLM or an earlier extension already set X-Agent-Scope?
        # If so, respect that value — do not overwrite.
        existing_headers = tool_args.get("headers") or {}
        if isinstance(existing_headers, dict) and "X-Agent-Scope" in existing_headers:
            return

        # Pull prepared headers from agent.data carrier (populated by
        # mentor_subordinate_invoker.py when the orchestrator spawned this
        # subordinate agent under a mentor pipeline run).
        try:
            carried = self.agent.get_data("_outbound_headers")
        except Exception:
            carried = None

        if not carried:
            return  # no-op — agent not under a mentor pipeline

        # Merge: start with orchestrator-carried headers, then overlay any
        # existing headers so caller-set keys (other than X-Agent-Scope) win.
        merged = dict(carried)
        if isinstance(existing_headers, dict):
            merged.update(existing_headers)
        tool_args["headers"] = merged

        try:
            logger.debug(
                "auto-injected scope headers for tool=%s",
                tool_name or "(unknown)",
            )
        except Exception:
            pass
