# Phase 47.6 Wave 1: dual-mode behind REGISTRY_DRIVEN_INDEX feature flag.
# Default false (walker path) — Wave 4 (Plan 07) flips to default-true and DELETES the walker branch.
# See .planning/phases/47.6-*/47.6-RESEARCH.md §Pattern 6.
import os
from typing import Any

from helpers.extension import Extension, extensible
from helpers import files, subagents
from helpers.print_style import PrintStyle
from agent import Agent, LoopData

# Feature flag: set REGISTRY_DRIVEN_INDEX=true to use the registry-driven index path.
# Default is false (walker path preserved for Wave 4 cutover safety).
# Wave 4 (Plan 07) will flip this to default-true and DELETE the walker branch.
REGISTRY_DRIVEN_INDEX: bool = os.environ.get("REGISTRY_DRIVEN_INDEX", "false").lower() == "true"

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
    if REGISTRY_DRIVEN_INDEX:
        # Registry-driven path (Phase 47.6 Plan 03).
        # Wave 4 (Plan 07) flips REGISTRY_DRIVEN_INDEX to default-true and deletes walker.
        from core.registry.capability_registry import CapabilityRegistry

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
    else:
        # ORIGINAL walker path — preserved verbatim for Wave 4 cutover safety.
        # Wave 4 (Plan 07) will delete this branch after snapshot-test parity is confirmed.

        # collect tool files from all prompt directories
        prompt_dirs = subagents.get_paths(agent, "prompts")
        tool_files = files.get_unique_filenames_in_dirs(
            prompt_dirs, "agent.system.tool.*.md"
        )

        # per-file kwargs registered by plugin config extensions (e.g. _09_text_editor_config)
        all_tool_kwargs: dict[str, dict[str, Any]] = agent.get_data(TOOL_KWARGS_KEY) or {}

        tools: list[str] = []
        for tool_file in tool_files:
            try:
                basename = os.path.basename(tool_file)
                extra = all_tool_kwargs.get(basename, {})
                tool = agent.read_prompt(basename, **extra)
                tools.append(tool)
            except Exception as e:
                PrintStyle().error(f"Error loading tool '{tool_file}': {e}")

        tools_str = "\n\n".join(tools)
        prompt = agent.read_prompt("agent.system.tools.md", tools=tools_str)

        # vision support
        from plugins._model_config.helpers.model_config import get_chat_model_config

        chat_cfg = get_chat_model_config(agent)
        if chat_cfg.get("vision", False):
            prompt += "\n\n" + agent.read_prompt("agent.system.tools_vision.md")

        return prompt
