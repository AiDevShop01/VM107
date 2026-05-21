"""BUG-23 / Phase 62.1: thinking_mode capability flag → provider-specific extra args.

Translates the optional `thinking_mode` field in an agent's sub-profile agent.yaml
into provider-specific LLM call parameters (extra_body) by monkey-patching
call_data["model"].unified_call — the same pattern used by _router_apply.py.

Design:
  - Reads `thinking_mode` from the agent's loaded SubAgent profile.
  - For DeepSeek providers: wraps unified_call to inject
    extra_body={"thinking": {"type": "enabled"|"disabled"}}.
  - For other providers: logs INFO/WARNING when thinking_mode is explicitly set
    to False but does NOT crash — falls through to model default (graceful no-op).
  - Idempotent: if extra_body["thinking"] is already set in the call kwargs,
    does NOT overwrite it.
  - Fires AFTER _router_apply.py (alphabetical sort: '_t' > '_r') so any model
    swap has already occurred before we inspect the model identifier.
  - Brain-preservation: agents with no thinking_mode field in agent.yaml →
    this extension is a no-op, preserving all existing behavior for brain agents.

Monkey-patch wire-site (same as _router_apply.py):
  agent.py:821 calls call_data["model"].unified_call(**kwargs).
  Replacing unified_call on the instance is safe — LiteLLMChatWrapper has
  model_config = ConfigDict(extra="allow", validate_assignment=False).

Provider mapping (extend here as new providers add thinking-mode support):
  deepseek/*  → extra_body={"thinking": {"type": "enabled"|"disabled"}}
"""
from __future__ import annotations

import logging

from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("fingpt.chat_model_call_before.thinking_mode_toggle")

_AGENT_PROFILE_THINKING_CACHE_KEY = "_bug23_thinking_cache"


def _resolve_thinking_mode(agent) -> bool | None:
    """Return the thinking_mode for the agent's current profile, or None if not set.

    None means the field was absent in agent.yaml — no injection.
    True  means explicitly thinking enabled.
    False means explicitly thinking disabled.

    Caches on agent.data to avoid repeated SubAgent loads per monologue loop.
    """
    if not agent:
        return None

    profile = getattr(getattr(agent, "config", None), "profile", "")
    if not profile:
        return None

    # Store as dict {"value": <bool|None>} so None is a cacheable value
    cache_store = agent.data.get(_AGENT_PROFILE_THINKING_CACHE_KEY)
    if isinstance(cache_store, dict) and "value" in cache_store:
        return cache_store["value"]

    thinking_mode: bool | None = None  # safe default: no injection
    try:
        from helpers import subagents
        sub = subagents.load_agent_data(profile)
        thinking_mode = getattr(sub, "thinking_mode", None)
    except Exception as exc:
        log.debug(
            "BUG-23: could not load SubAgent for profile %r to read thinking_mode: %s"
            " — no injection",
            profile, exc,
        )

    agent.data[_AGENT_PROFILE_THINKING_CACHE_KEY] = {"value": thinking_mode}
    return thinking_mode


def _get_model_identifier(call_data: dict) -> str:
    """Extract the model identifier string from call_data['model'] if available."""
    model = call_data.get("model")
    if model is None:
        return ""
    name = getattr(model, "model_name", None)
    if name:
        return str(name)
    return ""


def _is_deepseek_model(model_id: str) -> bool:
    """Return True if the model identifier indicates a DeepSeek provider."""
    lower = model_id.lower()
    return (
        lower.startswith("deepseek/")
        or lower.startswith("deepseek-v4")
        or lower.startswith("deepseek-r")
    )


def _wrap_unified_call_with_thinking(call_data: dict, enabled: bool, profile: str) -> None:
    """Monkey-patch call_data['model'].unified_call to inject extra_body.thinking.

    Idempotent: if the kwargs already contain extra_body with a 'thinking' key,
    the patch does NOT overwrite it.

    Uses the same instance-method replacement pattern as _router_apply.py.
    """
    original_unified_call = call_data["model"].unified_call
    thinking_type = "enabled" if enabled else "disabled"

    async def _unified_call_with_thinking(**kw):
        # Idempotent: do not overwrite upstream-set thinking value
        existing_extra_body = kw.get("extra_body", {})
        if "thinking" not in existing_extra_body:
            merged_extra_body = dict(existing_extra_body)
            merged_extra_body["thinking"] = {"type": thinking_type}
            kw["extra_body"] = merged_extra_body
            log.debug(
                "BUG-23: injecting extra_body.thinking.type=%r for profile %r",
                thinking_type, profile,
            )
        else:
            log.debug("BUG-23: extra_body.thinking already set upstream — not overwriting")
        return await original_unified_call(**kw)

    call_data["model"].unified_call = _unified_call_with_thinking


class ThinkingModeToggle(Extension):
    """chat_model_call_before extension: translates thinking_mode flag to provider args.

    Fires after _router_apply.py (alphabetical order within the hook directory),
    so any model swap has already taken effect before this extension inspects
    call_data["model"].
    """

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        call_data: dict = None,
        **kwargs,
    ):
        if not call_data or not self.agent:
            return

        thinking_mode = _resolve_thinking_mode(self.agent)
        if thinking_mode is None:
            # Field absent in agent.yaml — no injection, brain default preserved
            return

        model_id = _get_model_identifier(call_data)
        profile = getattr(getattr(self.agent, "config", None), "profile", "")

        if _is_deepseek_model(model_id):
            try:
                _wrap_unified_call_with_thinking(call_data, enabled=thinking_mode, profile=profile)
                log.debug(
                    "BUG-23: profile=%r model=%r thinking_mode=%r"
                    " → unified_call wrapped with extra_body.thinking.type=%r",
                    profile, model_id, thinking_mode,
                    "enabled" if thinking_mode else "disabled",
                )
            except Exception as patch_err:
                # Non-fatal: log and fall through without the patch
                log.warning(
                    "BUG-23: failed to wrap unified_call for thinking_mode on profile %r: %s"
                    " — falling through to model default",
                    profile, patch_err,
                )
        else:
            # Non-DeepSeek provider: log but do NOT crash
            if not thinking_mode:
                log.info(
                    "BUG-23: thinking_mode=false set for profile %r but model %r is not a "
                    "DeepSeek model — thinking_mode toggle not implemented for this provider. "
                    "Falling through to model default.",
                    profile, model_id,
                )
