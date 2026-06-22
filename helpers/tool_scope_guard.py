"""helpers/tool_scope_guard.py — Execution-level tool-scope guard.

Phase 89.1 Plan 03 Round 2 (REQ-89-9.3 loop-back fix):

Problem addressed:
    The prompt-level filter (_05_tool_scope_filter.py) hides denied tool
    DESCRIPTIONS from the LLM but does NOT prevent the LLM from invoking
    denied tools by name. The LLM hallucinates code_execution_tool calls,
    receives CapabilityRefusedError, then retries with variations (terminal /
    python3 / curl / memory_load …) 3-6× × 30-60s each — blowing past
    VM100's 180s dispatcher cap (89.1-05 v4 root-cause analysis).

Fix strategy:
    check_tool_scope_for_profile() is called at the top of agent.process_tools()
    immediately after tool_name is extracted from the LLM response.  If the tool
    is out-of-scope for the active profile, it returns a structured JSON string
    that the caller injects into hist_add_tool_result() — the LLM sees a polite
    "not in scope" response, NOT a retry-triggering exception.

Design principles:
    - Pure function: no agent / Flask / Dagster dependencies (unit-testable in CI).
    - Returns None (allowed) or str (JSON refusal payload) — never raises.
    - Type-safe against all profile shapes (None, str, dict).
    - Deny wins on collision (same rule as apply_tool_scope).
    - allowed_tools=None with denied_tools set: denies listed, rest allowed.
    - allowed_tools set: only those tools are permitted.

Public API:
    check_tool_scope_for_profile(tool_name, agent_profile) -> str | None

    TOOL_NOT_IN_SCOPE_ERROR: str  — the canonical error tag in the refusal payload.

Caller contract (agent.py process_tools):
    refusal = check_tool_scope_for_profile(tool_name, self.profile)
    if refusal is not None:
        self.hist_add_tool_result(tool_name, refusal)
        return  # short-circuit; LLM sees refusal and picks an allowed tool

The refusal payload JSON shape:
    {
        "error": "tool_not_in_scope",
        "tool_name": "<name>",
        "allowed_tools": ["<allowed_1>", ...],
        "message": "This tool is not available in the current agent scope. ..."
    }
"""
from __future__ import annotations

import json
from typing import Any

TOOL_NOT_IN_SCOPE_ERROR: str = "tool_not_in_scope"


def check_tool_scope_for_profile(
    tool_name: str,
    agent_profile: Any,
) -> str | None:
    """Check whether ``tool_name`` is permitted by the agent's profile scope.

    Returns
    -------
    None
        Tool is in scope — caller should proceed normally.
    str (JSON)
        Tool is OUT of scope — a structured refusal payload that the caller
        should inject into ``hist_add_tool_result(tool_name, <return_value>)``
        so the LLM sees a polite refusal and does NOT retry with variations.

    Rules (mirrors apply_tool_scope logic):
    - profile is None or a plain string → no scope restriction → return None.
    - profile is a dict without allowed_tools or denied_tools → return None.
    - allowed_tools=[...] → only tools in the list are permitted.
    - denied_tools=[...] → tools in the list are denied (regardless of allowed).
    - deny wins on collision: if tool is in both allowed and denied → denied.
    - Empty allowed_tools list treated as no restriction (defensive; avoids
      locking every tool by mistake on misconfigured profiles).
    """
    if not isinstance(agent_profile, dict):
        return None  # None or legacy string — no scope restriction

    allowed: list[str] | None = agent_profile.get("allowed_tools")
    denied: list[str] | None = agent_profile.get("denied_tools")

    if not allowed and not denied:
        return None  # no scope keys — explicit no-op

    # Normalise: treat empty list as None (defensive — avoids locking all tools)
    if allowed is not None and len(allowed) == 0:
        allowed = None

    # --- Deny check (deny wins on collision) ---
    if denied and tool_name in denied:
        return _build_refusal(tool_name, allowed, denied, reason="denied")

    # --- Allowed check ---
    if allowed is not None and tool_name not in allowed:
        return _build_refusal(tool_name, allowed, denied, reason="not_in_allowed")

    return None  # tool is in scope


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_refusal(
    tool_name: str,
    allowed: list[str] | None,
    denied: list[str] | None,
    reason: str,
) -> str:
    """Build the structured JSON refusal payload.

    The LLM receives this as a tool result, sees ``error=tool_not_in_scope``,
    and is instructed (via the system prompt) not to retry with variations but
    instead to pick an allowed tool or fall back to search_knowledge.
    """
    allowed_display: list[str] = list(allowed) if allowed else []

    if reason == "denied":
        message = (
            f"Tool '{tool_name}' is explicitly denied in the current agent scope. "
            f"Do NOT retry with variations or alternate tool names. "
            f"Pick one of the allowed tools listed below, or answer with "
            f"search_knowledge evidence and cite limitations explicitly."
        )
    else:
        message = (
            f"Tool '{tool_name}' is not in the allowed tool list for the current "
            f"agent scope. "
            f"Do NOT retry with variations or alternate tool names. "
            f"Use only the allowed tools listed below, or answer with "
            f"search_knowledge evidence and cite limitations explicitly."
        )

    payload = {
        "error": TOOL_NOT_IN_SCOPE_ERROR,
        "tool_name": tool_name,
        "allowed_tools": allowed_display,
        "message": message,
    }
    return json.dumps(payload)
