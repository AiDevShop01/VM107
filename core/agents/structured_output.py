"""Phase 43.2 — structured-output degradation primitives.

PORT SOURCES (verbatim TradingAgents):
  - bind_structured: tradingagents/agents/utils/structured.py:31-45
  - invoke_structured_or_freetext: tradingagents/agents/utils/structured.py:48-73
  - normalize_content: tradingagents/llm_clients/base_client.py:6-22

PIPELINE (safe_parse):
  Stage 1 (silent): schema.model_validate_json(output)
  Stage 2 (INFO log): repair_json(output) -> schema.model_validate*
  Stage 3 (WARNING log): PlainTextResult(degraded=True)

NEVER raises into the agent loop. Stage 3 always succeeds.

LOGGING DISCIPLINE:
  Stage 1: silent on success
  Stage 2 success: log.info({event: structured_repair_succeeded, schema, ...})
  Stage 3: log.warning({event: structured_fallback_plain_text, schema, error_chain})
  bind_structured unsupported: log.warning({event: structured_bind_unsupported, ...})
  invoke fallthrough: log.warning({event: structured_invoke_failed_falling_to_plain, ...})
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from json_repair import repair_json
from pydantic import BaseModel, ValidationError

log = logging.getLogger("agents.structured_output")


class PlainTextResult(BaseModel):
    """Wrapper returned by safe_parse when both strict and repair stages fail.

    Downstream agents detect degradation via:
        isinstance(result, PlainTextResult)
        # or
        getattr(result, "degraded", False)
    """

    raw_output: str
    schema_expected: str          # e.g. "Hypothesis"
    degraded: bool = True
    error_chain: list[str] = []   # populated by safe_parse with "stage_N_*: ExceptionName"


def bind_structured(llm: Any, schema: type[BaseModel], agent_name: str) -> Any | None:
    """Wrap llm with structured output binding; return None if provider doesn't support it.

    Verbatim port: tradingagents/agents/utils/structured.py:31-45
    With FinGPT logging conventions (json.dumps structured events).
    """
    try:
        return llm.with_structured_output(schema)
    except (AttributeError, NotImplementedError) as err:
        log.warning(json.dumps({
            "event": "structured_bind_unsupported",
            "agent": agent_name,
            "schema": schema.__name__,
            "error_class": type(err).__name__,
        }))
        return None


def invoke_structured_or_freetext(
    structured_llm: Any,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[Any], str],
    agent_name: str,
) -> Any:
    """Try structured invocation; fall back to plain LLM invoke on ANY failure.

    Verbatim port: tradingagents/agents/utils/structured.py:48-73
    With FinGPT logging conventions (json.dumps structured events).
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result)
        except Exception as err:
            log.warning(json.dumps({
                "event": "structured_invoke_failed_falling_to_plain",
                "agent": agent_name,
                "error_class": type(err).__name__,
                "error_message": str(err)[:300],
            }))

    response = plain_llm.invoke(prompt)
    log.info(json.dumps({
        "event": "plain_invoke_used",
        "agent": agent_name,
    }))
    return render(response)


def normalize_content(response: Any) -> str:
    """Normalize response.content to string. Handles: str, list of typed blocks.

    Verbatim port (extended): tradingagents/llm_clients/base_client.py:6-22
    Handles OpenAI Responses API + Anthropic + Gemini 3 content-block lists.
    Never raises.
    """
    try:
        content = getattr(response, "content", response)
    except Exception:
        return ""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # OpenAI Responses API: {"type": "text", "text": "..."}
                # Anthropic: {"type": "text", "text": "..."}
                # Gemini 3 reasoning blocks are skipped (only text/output_text is content)
                btype = block.get("type", "")
                if btype in ("text", "output_text"):
                    parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
            # Other shapes (None, ints, custom objects) silently skipped
        return "".join(parts)

    # Fallback: stringify whatever we got
    return str(content)


def safe_parse(output: str, schema: type[BaseModel]) -> BaseModel | PlainTextResult:
    """3-stage never-raising parse pipeline.

    Stage 1: schema.model_validate_json(output) — silent on success
    Stage 2: repair_json(output) -> validate — INFO log on success
    Stage 3: PlainTextResult(degraded=True) — WARNING log

    NEVER raises into the agent loop. Stage 3 always succeeds.
    Pitfall 3 (research): repair_json returns str OR dict/list — type check before model_validate*.
    """
    error_chain: list[str] = []

    # Stage 1: strict
    try:
        return schema.model_validate_json(output)
    except (ValidationError, ValueError, json.JSONDecodeError) as err:
        error_chain.append(f"stage_1_strict: {type(err).__name__}")

    # Stage 2: repair + validate
    try:
        repaired = repair_json(output)
        # Pitfall 3 (research): repair_json returns str OR dict/list
        if isinstance(repaired, str):
            result = schema.model_validate_json(repaired)
        else:
            result = schema.model_validate(repaired)
        log.info(json.dumps({
            "event": "structured_repair_succeeded",
            "schema": schema.__name__,
        }))
        return result
    except (ValidationError, ValueError, json.JSONDecodeError, TypeError) as err:
        error_chain.append(f"stage_2_repair: {type(err).__name__}")
    except Exception as err:
        # Defensive: json-repair could in theory raise unexpected errors
        error_chain.append(f"stage_2_unexpected: {type(err).__name__}")

    # Stage 3: plain-text wrapper (always succeeds)
    log.warning(json.dumps({
        "event": "structured_fallback_plain_text",
        "schema": schema.__name__,
        "error_chain": error_chain,
    }))
    return PlainTextResult(
        raw_output=output,
        schema_expected=schema.__name__,
        degraded=True,
        error_chain=error_chain,
    )
