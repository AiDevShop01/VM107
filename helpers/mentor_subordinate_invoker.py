"""Real Agent Zero subordinate invocation adapter for the Phase 60 mentor pipeline.

Replaces the _stub_invoker in Dagster mentor_jobs.py (Phase 60.1 gap closure G6+G21+G1).

Contract:
    async def invoke_mentor_subordinate(profile: str, input: BaseModel) -> dict
        - Spawns a fresh Agent Zero subordinate at depth=0 with the requested profile
        - Marshals the Pydantic input to UserMessage(message=json) (CTX-§3 hard-fail boundary 1)
        - Calls subordinate.monologue() (returns string per Agent Zero contract)
        - Parses the returned string as JSON; returns the dict
        - Seals subordinate history for compression (matches tools/call_subordinate.py:36)

Failure modes:
    - JSON parse failure → MentorSubordinateInvokerError(raw_output=<string>)
    - Pydantic-level contract violation downstream → orchestrator handles
      (this adapter does NOT call model_validate; it returns the parsed dict)

Architecture note:
    Dagster ops run in their own worker threads with no pre-existing parent
    AgentContext — so we cannot use the call_subordinate.py pattern verbatim
    (which assumes self.agent.context exists). Instead we instantiate a
    fresh AgentContext and a depth-0 Agent (number=0), which is the
    "no parent context" headless Dagster execution pattern.

Test injection seam:
    _SUBORDINATE_FACTORY is module-level and can be monkeypatched in tests to
    inject a fake subordinate that does NOT require a live Agent Zero runtime.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel

logger = logging.getLogger("fingpt.mentor.subordinate_invoker")


class MentorSubordinateInvokerError(Exception):
    """Raised when monologue() returns a string that is not valid JSON.

    Attaches the raw monologue text on ``.raw_output`` so callers (Dagster ops,
    red-team UAT) can record what the LLM produced for debugging.
    """

    def __init__(self, message: str, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class _SubordinateLike(Protocol):
    """Structural type for an Agent Zero subordinate (for testing).

    Real implementation is ``agent.Agent``; tests pass a fake matching this shape.
    """

    async def monologue(self) -> str: ...
    def hist_add_user_message(self, msg: Any) -> None: ...

    @property
    def history(self) -> Any: ...


# Factory injection seam — production code uses _spawn_real_agent_zero_subordinate;
# tests monkey-patch this to inject a fake. See test file for usage.
_SUBORDINATE_FACTORY = None  # replaced below after function definition


def _spawn_real_agent_zero_subordinate(profile: str) -> _SubordinateLike:
    """Spawn a fresh top-level Agent Zero subordinate for the requested profile.

    Dagster ops run in their own worker threads with no pre-existing parent
    AgentContext — so we cannot use the call_subordinate.py pattern verbatim
    (which assumes self.agent.context exists). Instead we instantiate a
    fresh AgentContext and a depth-0 Agent, then return that Agent for
    monologue() invocation.

    Imports are local to the function so module import remains cheap and the
    test suite can fake the factory without pulling in Agent Zero runtime deps.
    """
    from agent import Agent, AgentContext  # noqa: F401
    from initialize import initialize_agent

    config = initialize_agent()
    config.profile = profile  # e.g. "trade_auditor_agent._reader"
    context = AgentContext(config=config)
    return Agent(0, config, context)


_SUBORDINATE_FACTORY = _spawn_real_agent_zero_subordinate


async def invoke_mentor_subordinate(
    profile: str,
    input: BaseModel,
    *,
    headers: dict | None = None,
) -> dict:
    """Invoke an Agent Zero sub-profile and return the parsed JSON dict.

    Args:
        profile: Dotted sub-profile name, e.g. "trade_auditor_agent._reader"
        input:   Pydantic model (ReaderInput / AnalyzerInput / WriterInput)
        headers: Optional scope headers dict (Phase 60.1 G10/G22). When provided,
                 X-Agent-Scope and any other headers are pushed into agent.data under
                 '_outbound_headers' so Tool subclass wrappers (60-14) can read them
                 via self.agent.get_data('_outbound_headers').

    Returns:
        dict — parsed monologue JSON; downstream orchestrator calls model_validate

    Raises:
        MentorSubordinateInvokerError — monologue returned non-JSON string
    """
    # Local import keeps module-import-time cost minimal and helps tests fake.
    from agent import UserMessage

    subordinate = _SUBORDINATE_FACTORY(profile)

    # Phase 60.1 (G10/G22): expose scope headers to tool subclass wrappers.
    # Tool wrappers read headers from self.agent.get_data("_outbound_headers") (60-14).
    # CTX-§5 LOCKED: subordinates NEVER sign their own scope — headers are prepared
    # by the orchestrator and pushed down here as a carry-through carrier.
    if headers:
        try:
            subordinate.set_data("_outbound_headers", dict(headers))
        except AttributeError:
            # fakes may not implement set_data; tests pass a fake.data dict directly
            if hasattr(subordinate, "data"):
                subordinate.data["_outbound_headers"] = dict(headers)

    serialized = input.model_dump_json()
    subordinate.hist_add_user_message(UserMessage(message=serialized, attachments=[]))

    raw: str = await subordinate.monologue()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(
            "mentor_subordinate_invoker: profile=%s returned non-JSON string (len=%d)",
            profile,
            len(raw or ""),
        )
        raise MentorSubordinateInvokerError(
            f"profile={profile} returned non-JSON monologue (len={len(raw or '')})",
            raw_output=raw or "",
        ) from exc

    # 60-23: Agent Zero subagents commonly return output via the `response` tool,
    # wrapping content as {"tool_name": "response", "tool_args": {"text": "<inner>"}}.
    # When the LLM emits this convention, the inner `text` field carries the actual
    # contract payload. Unwrap so downstream model_validate sees the raw payload.
    # Backward-compat: if monologue() already returned raw contract JSON, keep it.
    if (
        isinstance(parsed, dict)
        and parsed.get("tool_name") == "response"
        and isinstance(parsed.get("tool_args"), dict)
        and isinstance(parsed["tool_args"].get("text"), str)
    ):
        inner_text = parsed["tool_args"]["text"]
        try:
            inner_parsed = json.loads(inner_text)
            parsed = inner_parsed
        except json.JSONDecodeError:
            # BUG-13 (Phase 62.1): Try to extract the outermost {...} block from
            # prose-wrapped output before falling through to the prose sentinel.
            # LLMs frequently emit "Here is the result: { ...valid JSON... } Thanks!"
            # — recover the JSON when it's structurally extractable.
            import re as _re
            _match = _re.search(r"\{.*\}", inner_text, _re.DOTALL)
            if _match:
                try:
                    _extracted = json.loads(_match.group(0))
                    logger.warning(
                        "mentor_subordinate_invoker: profile=%s extracted JSON block from prose-wrapped tool_args.text (extraction len=%d / inner len=%d) — BUG-13 extraction guard fired",
                        profile,
                        len(_match.group(0)),
                        len(inner_text),
                    )
                    parsed = _extracted
                    # success — skip the prose sentinel
                    inner_text = None  # signal that we recovered
                except json.JSONDecodeError:
                    pass  # extracted block was also invalid; fall to sentinel
            if inner_text is not None:
                # Extraction did not recover; preserve the existing sentinel path
                logger.warning(
                    "mentor_subordinate_invoker: profile=%s response.tool_args.text is prose, not JSON (len=%d) — BUG-13 extraction guard found no recoverable block",
                    profile,
                    len(inner_text),
                )
                parsed = {
                    "_unwrapped_prose": inner_text,
                    "_orig_tool_call": parsed,
                }

    # Seal topic for compression (mirrors tools/call_subordinate.py:36)
    try:
        subordinate.history.new_topic()
    except Exception:  # pragma: no cover — defensive; some fakes may not implement
        logger.debug("subordinate.history.new_topic() unavailable; skipping seal")

    return parsed
