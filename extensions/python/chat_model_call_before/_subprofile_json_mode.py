"""Phase 62.1 BUG-22 — force JSON mode on reader/analyzer/writer sub-profile LLM calls.

Sub-profiles (trade_auditor_agent._reader, behavioral_mentor_agent._analyzer, etc.)
are structured-output pipeline stages whose monologue MUST return valid JSON.

DeepSeek and similar models occasionally emit markdown audit reports with embedded
JSON instead of pure JSON tool calls even when the system prompt explicitly says
"respond with JSON". The DeepSeek API supports response_format={"type":"json_object"}
(OpenAI-compatible), which forces the model to emit only valid JSON.

This extension fires on the chat_model_call_before hook (same wire-site as
_router_apply.py). When the calling agent's profile ends with a recognised
sub-profile suffix (_reader, _analyzer, _writer), it monkey-patches
call_data["model"].unified_call to inject response_format={"type":"json_object"}
before delegating to the real unified_call.

Implementation notes:
  - Only sub-profiles are patched (profile ends with ._reader / ._analyzer / ._writer).
    The parent agent loop retains natural reasoning/thoughts output.
  - The patch is applied at call-time (not import-time) so the correct model instance
    (possibly already swapped by _router_apply.py) is targeted.
  - If call_data["model"] does not have a unified_call attribute (edge case / test
    double), the extension is a graceful no-op.
  - DeepSeek requires the word "json" somewhere in the prompt text when json_object
    mode is set. All sub-profile role.md prompts already contain "json" extensively
    (confirmed Plan 62.1-04 review).

Wire-site confirmation:
  agent.py:821  call_data["model"].unified_call(messages=..., ...)
  Replacing unified_call on the instance is safe — LiteLLMChatWrapper uses
  model_config = ConfigDict(extra="allow", validate_assignment=False).
"""
import logging

from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("fingpt.chat_model_call_before.subprofile_json_mode")

# Sub-profile suffixes that require structured JSON output.
# Profiles matching <anything>._reader | ._analyzer | ._writer trigger the patch.
_SUB_PROFILE_SUFFIXES = ("._reader", "._analyzer", "._writer")


def _profile_is_subprofile(profile: str) -> bool:
    """Return True when profile is a recognised structured-output sub-profile."""
    return any(profile.endswith(suffix) for suffix in _SUB_PROFILE_SUFFIXES)


class SubprofileJsonMode(Extension):
    """Inject response_format=json_object for structured-output sub-profile stages.

    Fires on chat_model_call_before. Monkey-patches call_data["model"].unified_call
    when the agent is running as a sub-profile (_reader / _analyzer / _writer).
    """

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        call_data: dict = None,
        **kwargs,
    ):
        if not call_data or not self.agent:
            return

        profile = getattr(getattr(self.agent, "config", None), "profile", "") or ""
        if not profile or not _profile_is_subprofile(profile):
            return

        model = call_data.get("model")
        if model is None or not hasattr(model, "unified_call"):
            log.warning(
                "subprofile_json_mode: profile=%s — call_data['model'] has no unified_call; "
                "skipping response_format injection (BUG-22)",
                profile,
            )
            return

        original_unified_call = model.unified_call

        async def _json_mode_unified_call(**kw):
            """Wrap unified_call, injecting response_format=json_object."""
            if "response_format" not in kw:
                kw["response_format"] = {"type": "json_object"}
            return await original_unified_call(**kw)

        model.unified_call = _json_mode_unified_call
        log.debug(
            "subprofile_json_mode: profile=%s — response_format=json_object patch installed (BUG-22)",
            profile,
        )
