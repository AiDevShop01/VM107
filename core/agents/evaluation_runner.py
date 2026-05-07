"""Mode B pre-trade evaluation runner.

Reads conversation history from VM107 Mongo (agent_envelopes collection),
calls LiteLLM with response_format=json_object + schema injected in prompt,
runs safe_parse with retry-once-then-fail, injects system fields via model_copy,
writes envelope on EVERY run (success, degraded, or failure).

Mode A (chat) and Mode B (this file) MUST NOT share prompts or output paths.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import litellm

from core.agents.envelope_writer import build_envelope, write_envelope
from core.agents.invocation_exceptions import EvaluationContractViolation
from core.agents.structured_output import PlainTextResult, safe_parse
from core.contracts.schemas import PreTradeEvaluation
from helpers.files import get_abs_path
from helpers.mongo import get_mongo_db

log = logging.getLogger(__name__)

EVAL_MODEL = os.getenv("EVAL_MODEL", os.getenv("CHAT_MODEL", "deepseek/deepseek-v4-flash"))
PROMPT_PATH = "agents/agent0/prompts/agent.system.main.pre_trade_evaluation.md"


def _load_system_prompt() -> str:
    abs_path = get_abs_path(PROMPT_PATH)
    return Path(abs_path).read_text(encoding="utf-8")


def _build_messages(
    *,
    system_prompt: str,
    schema_json: str,
    journal_id: str,
    context_block: dict,
    history_docs: list[dict],
) -> list[dict]:
    """Construct LLM messages: system + context preamble + history + final trigger."""
    rendered_system = system_prompt.replace("{schema_json}", schema_json)
    msgs: list[dict] = [{"role": "system", "content": rendered_system}]

    # Context preamble as user turn
    preamble = (
        f"# Trade Setup Context\n"
        f"- journal_id: {journal_id}\n"
        f"- instrument: {context_block.get('instrument', '<unspecified>')}\n"
        f"- timeframe: {context_block.get('timeframe', '<unspecified>')}\n"
        f"- strategy_id: {context_block.get('strategy_id') or '<none>'}\n"
        f"- checklist_snapshot:\n{context_block.get('checklist_snapshot_text', '<none>')}\n"
    )
    msgs.append({"role": "user", "content": preamble})

    for doc in history_docs:
        if (doc or {}).get("status") == "failure":
            continue
        user_msg = (doc.get("input") or {}).get("message", "")
        agent_msg = (doc.get("output") or {}).get("response", "")
        if user_msg:
            msgs.append({"role": "user", "content": user_msg})
        if agent_msg:
            msgs.append({"role": "assistant", "content": agent_msg})

    msgs.append({
        "role": "user",
        "content": "Generate the formal pre-trade evaluation now. Respond with ONLY the JSON object.",
    })
    return msgs


async def _call_llm_structured(messages: list[dict], model: str = EVAL_MODEL) -> str:
    """Call LiteLLM JSON mode. Returns the string content from the response.

    This function is a module-level symbol so tests can patch it directly:
        patch("core.agents.evaluation_runner._call_llm_structured", new=mock)
    """
    # Resolve API key from Agent Zero's dotenv convention (API_KEY_DEEPSEEK).
    # LiteLLM expects DEEPSEEK_API_KEY env var by default; Agent Zero stores
    # under API_KEY_<SERVICE>. Pass api_key= explicitly to bridge.
    from models import get_api_key  # type: ignore[import]
    service = model.split("/", 1)[0] if "/" in model else model
    api_key = get_api_key(service)

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        api_key=api_key if api_key and api_key != "None" else None,
    )
    content = response.choices[0].message.content or ""
    return content


def _persist_envelope(
    *,
    db,
    task_id: str,
    journal_id: str,
    source_env_id: Optional[str],
    status: str,
    input_payload: dict,
    output_payload: dict,
) -> str:
    """Build and write an AgentEnvelope. Returns the envelope_id."""
    env = build_envelope(
        task_id=task_id,
        parent_task_id=None,
        agent_id="agent_zero",
        input_payload=input_payload,
        output_payload=output_payload,
        telemetry={"model_used": EVAL_MODEL, "reason_chain": [], "cost": {}},
        status=status,  # type: ignore[arg-type]
        source_envelope_id=source_env_id,
        journal_id=journal_id,
    )
    return write_envelope(db, env)


async def run_pre_trade_evaluation(
    *,
    journal_id: str,
    conversation_id: str,
    strategy_id: Optional[str],
    user_id: str,
    context_block: dict,
    db,
    task_id: Optional[str] = None,
) -> tuple[PreTradeEvaluation, str, str]:
    """Run Mode B pre-trade evaluation.

    Reads conversation history from VM107 Mongo (NOT from request body),
    calls LiteLLM with response_format=json_object, retries once on PlainTextResult,
    injects system fields via model_copy after successful safe_parse,
    and writes an AgentEnvelope on EVERY run path (success, degraded attempt, failure).

    Returns:
        (evaluation, envelope_id, task_id)

    Raises:
        EvaluationContractViolation: Both LLM attempts returned unstructured output.
            envelope_id attribute is set to the failure envelope's id.
        Exception: LLM hard failure (network, provider error). Failure envelope persisted.
    """
    task_id = task_id or f"eval-{uuid.uuid4().hex}"

    # 1. Read conversation history from Mongo (NOT received in body — RESEARCH Critical Finding #3)
    cursor = db["agent_envelopes"].find(
        {"journal_id": journal_id, "agent_id": "agent_zero"},
        sort=[("timestamp", 1)],
    )
    history_docs = list(cursor)
    history_docs.sort(key=lambda d: (d or {}).get("timestamp", ""))

    # 2. Source envelope = most recent chat envelope for this journal
    prev_doc = db["agent_envelopes"].find_one(
        {"journal_id": journal_id, "agent_id": "agent_zero"},
        sort=[("timestamp", -1)],
    )
    source_env_id: Optional[str] = (prev_doc or {}).get("envelope_id")

    # 3. Build prompt with live schema injected so LLM knows the exact shape
    system_prompt = _load_system_prompt()
    schema_json = json.dumps(PreTradeEvaluation.model_json_schema(), indent=2)
    messages = _build_messages(
        system_prompt=system_prompt,
        schema_json=schema_json,
        journal_id=journal_id,
        context_block=context_block,
        history_docs=history_docs,
    )

    input_payload = {
        "trigger": "generate_formal_evaluation",
        "conversation_id": conversation_id,
        "strategy_id": strategy_id,
        "user_id": user_id,
        "context": context_block,
        "history_count": len(history_docs),
    }

    # 4. Retry-once-then-fail loop (mirrors invocation.py lines 219-285 pattern)
    error_chain: list[str] = []
    last_raw: str = ""
    attempt = 0

    while attempt < 2:
        attempt += 1
        try:
            raw_content = await _call_llm_structured(messages)
        except Exception as exc:
            log.warning(
                "evaluation LLM hard failure attempt=%d: %s", attempt, exc
            )
            # Persist failure envelope before re-raising
            envelope_id = _persist_envelope(
                db=db,
                task_id=task_id,
                journal_id=journal_id,
                source_env_id=source_env_id,
                status="failure",
                input_payload=input_payload,
                output_payload={"error": str(exc), "attempt": attempt},
            )
            raise

        last_raw = raw_content
        result = safe_parse(raw_content, PreTradeEvaluation)

        if not isinstance(result, PlainTextResult):
            # Success — inject system fields via model_copy (Pydantic v2 frozen model safe)
            evaluation_id = str(uuid.uuid4())
            now_utc = datetime.now(timezone.utc)
            evaluation = result.model_copy(update={
                "evaluation_id": evaluation_id,
                "trade_id": journal_id,
                "conversation_id": conversation_id,
                "source_envelope_id": source_env_id or "",
                "created_at": now_utc,
                "strategy_id": strategy_id if strategy_id is not None else result.strategy_id,
            })
            envelope_id = _persist_envelope(
                db=db,
                task_id=task_id,
                journal_id=journal_id,
                source_env_id=source_env_id,
                status="success",
                input_payload=input_payload,
                output_payload={"evaluation": evaluation.model_dump(mode="json")},
            )
            return evaluation, envelope_id, task_id

        # PlainTextResult — accumulate error chain, persist degraded envelope for provenance
        error_chain.extend(result.error_chain)
        log.warning(
            "evaluation_runner degraded attempt=%d/2 error_chain=%s",
            attempt,
            result.error_chain,
        )
        _persist_envelope(
            db=db,
            task_id=task_id,
            journal_id=journal_id,
            source_env_id=source_env_id,
            status="degraded",
            input_payload=input_payload,
            output_payload={
                "plain_text": result.raw_output[:2000],
                "error_chain": result.error_chain,
                "attempt": attempt,
            },
        )

    # Both attempts degraded — write failure envelope, then raise EvaluationContractViolation
    failure_env_id = _persist_envelope(
        db=db,
        task_id=task_id,
        journal_id=journal_id,
        source_env_id=source_env_id,
        status="failure",
        input_payload=input_payload,
        output_payload={
            "error": "EvaluationContractViolation",
            "error_chain": error_chain,
            "last_raw_truncated": last_raw[:1000],
        },
    )
    exc = EvaluationContractViolation(error_chain=error_chain, envelope_id=failure_env_id)
    raise exc
