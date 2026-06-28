"""Phase 89.1 Plan 03 (REQ-89-9.3) — Profile-driven tool-scope filter extension.

A0 tool registry location (resolved during plan revision):
    The tool list seen by the LLM is built lazily by
    extensions/python/system_prompt/_11_tools_prompt.py via
    CapabilityRegistry.get().get_index_for_profile(profile_id).

Integration mechanism — "stash filtered index, downstream prefers it":
    This extension (_05_*) runs BEFORE _11_tools_prompt.py in the numerical
    system_prompt extension chain (_05 → _10 → _11 → _12 → _13 → _14).
    When the agent's profile dict contains allowed_tools or denied_tools,
    this extension:
      1. Fetches the full CapabilityRegistry index for the agent's profile.
      2. Applies apply_tool_scope() to produce a constrained list[dict].
      3. Stashes the result in agent state via
         agent.set_data("_tool_scope_filtered_index", filtered).
    Then _11_tools_prompt.build_prompt() prefers the stashed filtered index
    when present (via agent.get_data("_tool_scope_filtered_index")).

No-op paths (no stash, registry path unchanged):
    - agent.profile is a plain string  (legacy / non-macro agents)
    - agent.profile is a dict without allowed_tools or denied_tools keys
    - self.agent is None / not set

This design has zero blast radius on non-macro agents that use the default
A0 tool set — _11_tools_prompt falls back to the registry path exactly as
before if the stash is absent.
"""
from typing import Any

from helpers.extension import Extension
from agent import Agent, LoopData
from helpers.tool_scope import apply_tool_scope
from core.registry.capability_registry import CapabilityRegistry


class ToolScopeFilter(Extension):
    """system_prompt extension — applies allowed/denied tool scope from agent profile.

    Numbered _05_* so it runs BEFORE _11_tools_prompt.py (alphabetical / numerical
    ordering within the system_prompt extension folder).

    Only active when agent.profile is a dict with at least one of allowed_tools /
    denied_tools.  All other agents pass through with no side-effect.
    """

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        agent = self.agent
        # Agent.profile is not always present (base AgentConfig declares it but
        # the Agent instance may not surface it as an attribute on older base
        # images). Use getattr to match the existing safe pattern in agent.py.
        profile = getattr(agent, "profile", None) if agent else None
        if not isinstance(profile, dict):
            return  # legacy string profile or no agent → no scoping

        allowed: list[str] | None = profile.get("allowed_tools")
        denied: list[str] | None = profile.get("denied_tools")

        if not allowed and not denied:
            return  # bare dict profile with no scope keys → explicit no-op

        # Resolve profile_id for the registry lookup
        profile_id: str = (
            getattr(agent, "profile_id", None)
            or profile.get("id", "agent_zero")
        )

        # Fetch the full registry index for this profile then constrain it
        reg = CapabilityRegistry.get()
        full_index: list[dict] = reg.get_index_for_profile(profile_id)
        filtered: list[dict] = apply_tool_scope(full_index, allowed, denied)

        # Stash for _11_tools_prompt.build_prompt() to prefer
        agent.set_data("_tool_scope_filtered_index", filtered)

        agent.context.log.log(
            type="system_prompt",
            content=(
                f"tool_scope_filtered profile={profile_id} "
                f"allowed={len(allowed or [])} denied={len(denied or [])} "
                f"final={len(filtered)}"
            ),
        )
