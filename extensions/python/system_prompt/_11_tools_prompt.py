"""Phase 47.6 Wave 4: registry-driven. Filesystem walker DELETED.

Source of truth for tool prompt assembly: CapabilityRegistry.get_index_for_profile().
Old walker (pre-47.6): walked prompt_dirs for agent.system.tool.*.md glob
(via helpers.files and helpers.subagents — DELETED in this wave).

Cutover validated by tests/extensions/test_11_tools_prompt.py snapshot parity
tests BEFORE deletion (Plan 07 Task 1).
"""
from typing import Any

from helpers.extension import Extension, extensible
from agent import Agent, LoopData

from core.registry.capability_registry import CapabilityRegistry

TOOL_KWARGS_KEY = "_tool_prompt_kwargs"


class ToolsPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        system_prompt.append(prompt)


@extensible
async def build_prompt(agent: Agent) -> str:
    """Registry-driven tool prompt assembly (Phase 47.6 Wave 4).

    Calls CapabilityRegistry.get().get_index_for_profile(profile_id) to
    retrieve the LD-4 profile-scoped capability index. Renders each entry
    in the compressed `id / short_description / impact` shape.

    Walker code (helpers.files and helpers.subagents directory scanning)
    has been DELETED. The registry is the only source of capability truth.
    Boot assertion in preload.py (assert_no_filesystem_walkers) guards against
    accidental re-introduction.

    Phase 89.1 Plan 03 (REQ-89-9.3): prefers the filtered index stashed by
    _05_tool_scope_filter.py when present.  Falls back to the full registry
    path for all agents that have no allowed_tools / denied_tools scope.
    """
    # Prefer filtered index stashed by _05_tool_scope_filter (Phase 89.1 Plan 03)
    filtered = agent.get_data("_tool_scope_filtered_index")
    if filtered is not None:
        index = filtered
    else:
        reg = CapabilityRegistry.get()
        profile_id = getattr(agent, "profile_id", "agent_zero")
        index = reg.get_index_for_profile(profile_id)
    tools_str = "\n\n".join(
        f"{e['id']}\n→ {e['short_description']}\n→ impact: {e['impact_on_decision']}"
        for e in index
    )
    prompt = agent.read_prompt("agent.system.tools.md", tools=tools_str)

    # vision support (same as walker path)
    from plugins._model_config.helpers.model_config import get_chat_model_config
    chat_cfg = get_chat_model_config(agent)
    if chat_cfg.get("vision", False):
        prompt += "\n\n" + agent.read_prompt("agent.system.tools_vision.md")

    return prompt
