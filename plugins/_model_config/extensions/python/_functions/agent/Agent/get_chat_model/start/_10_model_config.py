"""BUG-23 / Phase 62.1: model-tier routing via get_chat_model().

When an agent's loaded profile declares model_tier: utility, get_chat_model()
returns the globally-configured utility model instead of the chat model.
This routes mechanical sub-profile stages (readers) to the utility tier
without changing the brain agents (no model_tier field → chat tier unchanged).

Brain-preservation guarantee: agents whose profile has model_tier=None or
model_tier='chat' always receive build_chat_model() — identical to pre-BUG-23
behavior.
"""
import logging

from helpers.extension import Extension
from plugins._model_config.helpers.model_config import build_chat_model, build_utility_model

log = logging.getLogger("fingpt.model_config.get_chat_model")

_AGENT_PROFILE_TIER_CACHE_KEY = "_bug23_model_tier"


def _resolve_model_tier(agent) -> str:
    """Return 'utility' or 'chat' for the agent's current profile.

    Reads the SubAgent yaml data via load_agent_data(), caching the result on
    agent.data to avoid repeated disk reads within a single monologue loop.

    Returns 'chat' (default) if:
      - agent is None
      - profile name is empty
      - SubAgent has no model_tier field (backward-compat / brain profiles)
      - model_tier is explicitly 'chat'
    Returns 'utility' only when model_tier is explicitly 'utility'.
    """
    if not agent:
        return "chat"

    profile = getattr(getattr(agent, "config", None), "profile", "")
    if not profile:
        return "chat"

    # Cache the tier on agent.data to avoid repeated SubAgent loads.
    cached = agent.data.get(_AGENT_PROFILE_TIER_CACHE_KEY)
    if cached is not None:
        return cached

    tier = "chat"  # safe default
    try:
        from helpers import subagents
        sub = subagents.load_agent_data(profile)
        tier = getattr(sub, "model_tier", None) or "chat"
    except Exception as exc:
        log.debug("BUG-23: could not load SubAgent for profile %r: %s — defaulting to chat tier", profile, exc)

    agent.data[_AGENT_PROFILE_TIER_CACHE_KEY] = tier
    return tier


class ChatModelProvider(Extension):
    def execute(self, data: dict = {}, **kwargs):
        if self.agent:
            tier = _resolve_model_tier(self.agent)
            if tier == "utility":
                log.debug(
                    "BUG-23: profile %r has model_tier=utility — routing get_chat_model() to utility model",
                    self.agent.config.profile,
                )
                data["result"] = build_utility_model(self.agent)
            else:
                data["result"] = build_chat_model(self.agent)
