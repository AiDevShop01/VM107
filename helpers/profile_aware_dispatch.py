"""Profile-aware dispatch middleware for user-driven agent endpoints.

Path B decision (2026-06-22, 89.1-04-DISPATCH-DECISION-LOG.md):
  /api/api_message uses this middleware for synchronous user-driven agents.
  /helpers/task_scheduler.py handles asynchronous background agents separately.
  Two dispatch paths are INTENTIONAL — see decision log for full rationale.

Usage:
    from helpers.profile_aware_dispatch import load_profile_into_agent

    if agent_profile:
        try:
            load_profile_into_agent(context.agent0, agent_profile)
        except FileNotFoundError:
            log.warning(f"Profile {agent_profile} not found; legacy mode")

Contract guarantees:
  - agent0.profile is set to the loaded YAML dict (a real dict, not a string).
  - agent0.set_data("profile_id", profile_id) is called with the canonical id.
  - agent0.set_data("_system_prompt", <text>) is called when a matching
    prompts/{profile_id}.md file exists (empty string if file is absent but
    profile YAML is found).
  - Raises FileNotFoundError if the profile YAML does not exist — callers
    should catch and log a warning rather than swallowing silently.
  - On any OTHER error (YAML parse failure, permissions, etc.) the exception
    propagates uncaught so misconfiguration is visible.
  - Atomic: agent0 state is only mutated AFTER all reads succeed. If the
    YAML read succeeds but the prompt read fails, profile IS set (partial
    state is acceptable — system_prompt is optional).

Registry paths (canonical):
  YAML:   registry/agent_profile/{profile_id}.yaml
  Prompt: prompts/{profile_id}.md          (optional — silently skipped)

Both paths use helpers.files.get_abs_path() — the same filesystem layer that
task_scheduler uses — keeping the two dispatch paths drift-free.
"""
from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

import yaml as _yaml

from helpers import files as _files
from helpers.print_style import PrintStyle as _PrintStyle


# ---------------------------------------------------------------------------
# Agent0 protocol (structural typing — avoids circular import with agent.py)
# ---------------------------------------------------------------------------

@runtime_checkable
class _AgentLike(Protocol):
    """Structural type expected by load_profile_into_agent.

    Matches the production Agent class contract without importing it.
    """

    profile: Any  # dict when populated; may start as None/str on Agent.

    def set_data(self, field: str, value: Any) -> None:
        ...

    def get_data(self, field: str) -> Any:
        ...


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_profile_into_agent(
    agent0: _AgentLike,
    profile_id: str,
) -> dict:
    """Load a registry profile YAML and inject it into agent0.

    Mutates agent0 in place:
      - agent0.profile = loaded YAML dict
      - agent0.set_data("profile_id", profile_id)
      - agent0.set_data("_system_prompt", <text>)  — only when prompts/{id}.md exists

    Parameters
    ----------
    agent0:
        The agent instance whose profile/data slots will be populated.
        Must satisfy the _AgentLike protocol (profile attribute + get/set_data).
    profile_id:
        The canonical profile id, e.g. ``"vm107.macro_investigator"``.
        Must match a file at ``registry/agent_profile/{profile_id}.yaml``.

    Returns
    -------
    dict
        The loaded profile dict (same object assigned to agent0.profile).

    Raises
    ------
    FileNotFoundError
        If ``registry/agent_profile/{profile_id}.yaml`` does not exist.
        Callers should catch this and fall back to legacy (no-profile) mode.
    yaml.YAMLError
        If the profile YAML is malformed.
    OSError
        If the profile file exists but cannot be read (permissions, etc.).
    """
    profile_rel_path = f"registry/agent_profile/{profile_id}.yaml"

    # --- Phase 1: resolve and validate the profile YAML path ---
    try:
        profile_abs_path = _files.get_abs_path(profile_rel_path)
    except Exception as exc:
        # get_abs_path itself should not raise for a valid relative path, but
        # be defensive here to surface any misconfiguration.
        raise FileNotFoundError(
            f"profile_aware_dispatch: could not resolve profile path for "
            f"'{profile_id}': {exc}"
        ) from exc

    if not os.path.exists(profile_abs_path):
        raise FileNotFoundError(
            f"profile_aware_dispatch: profile YAML not found: {profile_abs_path}"
        )

    # --- Phase 2: load profile YAML ---
    with open(profile_abs_path, "r", encoding="utf-8") as _f:
        profile_dict: dict = _yaml.safe_load(_f) or {}

    # --- Phase 3: load system prompt (optional) ---
    # Prompt file naming convention: try two candidates in priority order:
    #   1. prompts/{profile_id}.md          (full dotted id, e.g. vm107.macro_investigator.md)
    #   2. prompts/{short_name}.md          (last segment only, e.g. macro_investigator.md)
    # The second fallback exists because legacy prompt files predate the vm107. prefix
    # convention (the original api_message.py used the short name). Both are valid.
    system_prompt: str = ""
    _short_name = profile_id.split(".")[-1] if "." in profile_id else profile_id
    _prompt_candidates = [
        f"prompts/{profile_id}.md",
        f"prompts/{_short_name}.md",
    ]
    # Deduplicate (handles the case where profile_id has no dots)
    _prompt_candidates = list(dict.fromkeys(_prompt_candidates))

    for prompt_rel_path in _prompt_candidates:
        try:
            prompt_abs_path = _files.get_abs_path(prompt_rel_path)
            if os.path.exists(prompt_abs_path):
                with open(prompt_abs_path, "r", encoding="utf-8") as _pf:
                    system_prompt = _pf.read()
                break  # found — stop searching
        except Exception as _exc:
            # Prompt load failure is non-fatal — profile is still usable.
            _PrintStyle.error(
                f"profile_aware_dispatch: failed to load system prompt from "
                f"'{prompt_rel_path}' for profile '{profile_id}': {_exc}"
            )
            break  # unexpected error — don't try next candidate

    if not system_prompt:
        _PrintStyle.debug(
            f"profile_aware_dispatch: no system prompt file found for '{profile_id}' "
            f"(tried: {_prompt_candidates}); profile loaded without system prompt"
        )

    # --- Phase 4: mutate agent0 (all reads succeeded) ---
    agent0.profile = profile_dict
    agent0.set_data("profile_id", profile_id)
    if system_prompt:
        agent0.set_data("_system_prompt", system_prompt)

    _PrintStyle.debug(
        f"profile_aware_dispatch: loaded profile '{profile_id}' "
        f"({'with' if system_prompt else 'without'} system prompt)"
    )

    return profile_dict
