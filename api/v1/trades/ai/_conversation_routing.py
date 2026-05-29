"""Phase 71 Plan 02 — conversation_type -> profile dispatch helper.

Single source of truth for the 6-mode homing table per Phase 71 CONTEXT
Decision 4 (hybrid 4c). chat.py calls this; do not duplicate the table
elsewhere.

Routing table (CONTEXT Decision 4):

    | conversation_type | host_agent_profile        | skill_addendum     |
    | ----------------- | ------------------------- | ------------------ |
    | pre_trade         | agent0 (Phase 47)         | None (unchanged)   |
    | execution_chat    | trade_auditor_agent       | execution_chat     |
    | reflection_chat   | behavioral_mentor_agent   | reflection_chat    |
    | strategy_chat     | weekly_review_agent       | strategy_chat      |
    | macro_chat        | macro_agent (NEW)         | None (dedicated)   |
    | research_chat     | research_chat_agent (NEW) | None (dedicated)   |

`pre_trade` / `macro_chat` / `research_chat` ride dedicated host profiles so
no skill addendum is needed; the three Phase 60 profiles
(trade_auditor / behavioral_mentor / weekly_review) gain a +chat skill
addendum because they are re-used out of their original review/audit role.
"""
from __future__ import annotations

from fingpt_core.contracts.ask_ai_binding import CONVERSATION_TYPES


# CONTEXT Decision 4 homing table.
_PROFILE_MAP: dict[str, str] = {
    "pre_trade": "agent0",                          # Phase 47 — unchanged
    "execution_chat": "trade_auditor_agent",        # Phase 60 profile + +execution_chat skill
    "reflection_chat": "behavioral_mentor_agent",   # Phase 60 profile + +reflection_chat skill
    "strategy_chat": "weekly_review_agent",         # Phase 60 profile + +strategy_chat skill
    "macro_chat": "macro_agent",                    # NEW dedicated profile (Plan 02 Task 2)
    "research_chat": "research_chat_agent",         # NEW dedicated profile (Plan 02 Task 2)
}

_SKILL_ADDENDUM: dict[str, str | None] = {
    "execution_chat": "execution_chat",
    "reflection_chat": "reflection_chat",
    "strategy_chat": "strategy_chat",
    # macro_chat / research_chat / pre_trade: no addendum (profile is dedicated/native).
}


class UnknownConversationType(ValueError):
    """Raised by chat.py to trigger a 400 response.

    Distinguishes a malformed `conversation_type` value (client error -> 400)
    from a runtime profile-bootstrap failure (server error -> 502).
    """


def conversation_type_to_profile(
    conversation_type: str | None,
) -> tuple[str, str | None]:
    """Resolve conversation_type to (profile_name, skill_addendum_or_None).

    Returns ``("agent0", None)`` when ``conversation_type`` is ``None``
    (backward-compatible default = Phase 47 pre_trade flow).

    Raises ``UnknownConversationType`` for non-canonical values (anything not
    in ``fingpt_core.contracts.ask_ai_binding.CONVERSATION_TYPES``).
    """
    if conversation_type is None:
        return "agent0", None
    if conversation_type not in CONVERSATION_TYPES:
        raise UnknownConversationType(
            f"conversation_type {conversation_type!r} not in "
            f"{sorted(CONVERSATION_TYPES)}"
        )
    profile = _PROFILE_MAP[conversation_type]
    skill = _SKILL_ADDENDUM.get(conversation_type)
    return profile, skill
