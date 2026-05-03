"""Phase 44 hard-tool-scope registry.

HARD-scoped tools are blocked at runtime for agents NOT in the allowed list.
Soft-scoped tools (search_knowledge, document_query, response, VM data clients)
have NO runtime block — they receive only prompt-level guidance.

Implementation pattern: per-profile denial stubs at agents/<profile>/tools/<tool>.py
override the global tool via subagents.get_paths() priority. Each stub raises
UnauthorizedToolError before any tool work happens.

Public API:
    UnauthorizedToolError — raised by denial stubs and check_tool_scope
    SENSITIVE_TOOLS       — frozenset of HARD-scoped tool names
    HARD_ALLOWED_TOOLS    — dict mapping agent_id → allowed sensitive tools
    PROFILE_TO_AGENT_ID   — dict mapping filesystem profile name → routing identity
    is_tool_allowed()     — returns bool (safe for conditional logic)
    check_tool_scope()    — raises UnauthorizedToolError on denial (used by denial stubs)
    resolve_agent_id_from_profile() — bridge profile name → agent_id
"""
from __future__ import annotations

from typing import Final


class UnauthorizedToolError(PermissionError):
    """Raised when an agent attempts to invoke a HARD-scoped tool not in its allow-list."""

    def __init__(self, agent_id: str, tool_name: str) -> None:
        self.agent_id = agent_id
        self.tool_name = tool_name
        super().__init__(
            f"Agent '{agent_id}' is not authorized to use tool '{tool_name}'. "
            f"Tool is HARD-scoped (Phase 44 tool_scope.py)."
        )


# Tools that are RUNTIME-BLOCKED (denial stub or extension raise) for agents not in HARD_ALLOWED_TOOLS.
# Adding a tool here means: (1) define HARD_ALLOWED_TOOLS entry, (2) add denial stub for blocked profiles.
SENSITIVE_TOOLS: Final[frozenset[str]] = frozenset({
    "call_subordinate",
    "code_execution_tool",
    # future: "trade_execution_tool"
})

# agent_id -> set of HARD-scoped tools the agent IS allowed to use.
# Agents not in this dict are denied ALL sensitive tools by default.
HARD_ALLOWED_TOOLS: Final[dict[str, frozenset[str]]] = {
    "agent_zero": frozenset({"call_subordinate", "code_execution_tool"}),
    "idea_agent": frozenset(),      # NO sensitive tools
    "strategy_agent": frozenset(),  # NO sensitive tools
}

# Filesystem profile name -> routing identity (Research § 3 + CONTEXT § Agent Identity).
PROFILE_TO_AGENT_ID: Final[dict[str, str]] = {
    "agent0": "agent_zero",
    "idea_agent": "idea_agent",
    "strategy_agent": "strategy_agent",
    "default": "default",
}


def is_tool_allowed(agent_id: str, tool_name: str) -> bool:
    """Return True if agent_id may invoke tool_name. Soft tools always return True."""
    if tool_name not in SENSITIVE_TOOLS:
        return True  # soft-scoped — prompt guidance only
    return tool_name in HARD_ALLOWED_TOOLS.get(agent_id, frozenset())


def check_tool_scope(agent_id: str, tool_name: str) -> None:
    """Raise UnauthorizedToolError if agent_id is not allowed to use tool_name.

    Soft-scoped tools (not in SENSITIVE_TOOLS) never raise.
    Used by denial stubs and extension hooks to enforce HARD scoping.
    """
    if not is_tool_allowed(agent_id, tool_name):
        raise UnauthorizedToolError(agent_id, tool_name)


def resolve_agent_id_from_profile(profile: str) -> str:
    """Bridge agent.config.profile (filesystem name) to router agent_id."""
    return PROFILE_TO_AGENT_ID.get(profile, profile)
