"""Phase 43.2 — structured-output degradation primitives.

PORT SOURCES (verbatim TradingAgents):
  - bind_structured: tradingagents/agents/utils/structured.py:31-45
  - invoke_structured_or_freetext: tradingagents/agents/utils/structured.py:48-73
  - normalize_content: tradingagents/llm_clients/base_client.py:6-22

PIPELINE (safe_parse):
  Stage 1 (silent): schema.model_validate_json(output)
  Stage 2 (INFO log): repair_json(output) -> schema.model_validate(repaired)
  Stage 3 (WARNING log): PlainTextResult(raw_output=..., schema_expected=..., degraded=True)

NEVER raises into the agent loop. Stage 3 always succeeds.

IMPLEMENTATION DEFERRED TO PLAN 03.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel


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
    """Try llm.with_structured_output(schema). Return None if unsupported. (PLAN 03 IMPLEMENTS.)"""
    raise NotImplementedError("Implemented in Plan 03 — Wave 1")


def invoke_structured_or_freetext(
    structured_llm: Any,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[Any], str],
    agent_name: str,
) -> Any:
    """Try structured invoke; fall back to plain on any failure. (PLAN 03 IMPLEMENTS.)"""
    raise NotImplementedError("Implemented in Plan 03 — Wave 1")


def normalize_content(response: Any) -> str:
    """Normalize response.content (string OR typed-block list) to str. (PLAN 03 IMPLEMENTS.)"""
    raise NotImplementedError("Implemented in Plan 03 — Wave 1")


def safe_parse(output: str, schema: type[BaseModel]) -> BaseModel | PlainTextResult:
    """3-stage never-raising parse: strict -> repair -> PlainTextResult. (PLAN 03 IMPLEMENTS.)"""
    raise NotImplementedError("Implemented in Plan 03 — Wave 1")
