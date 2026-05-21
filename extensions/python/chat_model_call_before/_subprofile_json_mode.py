"""Phase 62.1 BUG-22 — JSON mode investigation for reader/analyzer/writer sub-profile calls.

IMPLEMENTATION NOTE (2026-05-21):
  response_format={"type":"json_object"} was tested live against deepseek/deepseek-v4-flash
  and PROVED COUNTER-PRODUCTIVE in this Agent Zero context:

  - Agent Zero's tool-call protocol requires models to emit JSON in the shape
    {"tool_name": "...", "tool_args": {...}}.
  - JSON mode forces the model to emit ONLY valid JSON, but the model then emits
    bare ReaderOutput dicts instead of the response-tool-call wrapper.
  - This breaks the monologue loop: json_parse_dirty picks up the bare payload
    as a tool request → validate_tool_request raises "no tool_name" → the agent's
    error handler calls response tool with an error prose → monologue() returns
    prose → invoker gets non-JSON string.

  Net result: json_object mode makes failure mode change from "empty tool_name"
  to "non-JSON monologue" — a different error, not an improvement.

  Root cause: DeepSeek v4-flash emits valid but incorrectly-structured JSON when
  constrained by response_format. The right fix is at the prompt level (already
  done via role.md/specifics.md instructions) or model swap.

  This extension is kept as a GRACEFUL NO-OP so the infrastructure is in place
  for future use (e.g., a model that correctly wraps its output in tool-call JSON
  when json_object mode is active). The unit tests verify the plumbing works.

  FINDING RECORDED: see SUMMARY.md BUG-22 deviation note.
"""
import logging

from helpers.extension import Extension
from agent import LoopData

log = logging.getLogger("fingpt.chat_model_call_before.subprofile_json_mode")

# Sub-profile suffixes that would require structured JSON output if JSON mode were active.
_SUB_PROFILE_SUFFIXES = ("._reader", "._analyzer", "._writer")


def _profile_is_subprofile(profile: str) -> bool:
    """Return True when profile is a recognised structured-output sub-profile."""
    return any(profile.endswith(suffix) for suffix in _SUB_PROFILE_SUFFIXES)


class SubprofileJsonMode(Extension):
    """Infrastructure hook for JSON-mode injection on sub-profile LLM calls.

    Currently a GRACEFUL NO-OP — see module docstring for why json_object mode
    was tested and reverted. The plumbing (call_data patch, profile detection) is
    correct and tested; the activation is disabled pending a model that handles it.
    """

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        call_data: dict = None,
        **kwargs,
    ):
        # INTENTIONAL NO-OP: see module docstring.
        # json_object mode breaks deepseek-v4-flash's tool-call wrapper output.
        # The extension is kept (and tested) so the wiring is proven and ready
        # for future activation if/when a compatible model is configured.
        return
