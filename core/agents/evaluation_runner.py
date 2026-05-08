"""Mode B pre-trade evaluation runner — Phase 47.3 framework-first refactor.

Phase 47.3 5-step orchestration (LOCKED):

  Step 1 — Build ``EvaluationContext`` from Tier-1 + Tier-2 + Tier-3
           (Tier-2 fetches parallelized via ``asyncio.gather``).
  Step 2 — ``Framework().run(ctx)`` → ``PythonEngineResult`` (deterministic
           Python rules engine — Python owns score/recommendation/confidence).
  Step 3 — Build LLM messages with the ``## Framework Result`` block injected
           into the user content.
  Step 4 — Call LLM (single-shot + ``safe_parse`` retry-once-then-fail).
  Step 5 — ``model_copy(update={...})`` overwrite Python-owned fields onto
           the parsed LLM result. **CF-2 ENFORCEMENT** — without this step,
           the LLM silently controls scoring and Phase 47.3's deterministic
           guarantee is undone.
  Step 6 — Persist envelope (existing — Phase 44 lock).

Mode A (chat) and Mode B (this file) MUST NOT share prompts or output paths.
Mode A is unaffected by this refactor.

Backward compatibility:
  The function signature drops ``user_id``, ``context_block``, and ``db`` from
  the externally-required positional args (resolved internally). The API
  caller (``api/v1/trades/ai/evaluation.py``) is updated in Plan 06 to pass
  only the remaining kwargs and receive the returned ``PreTradeEvaluation``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import litellm

from core.agents.decision_framework.context import EvaluationContext
from core.agents.decision_framework.framework import Framework, PythonEngineResult
from core.agents.envelope_writer import build_envelope, write_envelope
from core.agents.invocation_exceptions import EvaluationContractViolation
from core.agents.strategy_loader import load_strategy
from core.agents.structured_output import PlainTextResult, safe_parse
from core.agents.tier1_context import build_tier1_context
from core.contracts.schemas import PreTradeEvaluation
from helpers.files import get_abs_path
from helpers.mongo import get_mongo_db

log = logging.getLogger(__name__)

EVAL_MODEL = os.getenv("EVAL_MODEL", os.getenv("CHAT_MODEL", "deepseek/deepseek-v4-flash"))
PROMPT_PATH = "agents/agent0/prompts/agent.system.main.pre_trade_evaluation.md"


# ---------------------------------------------------------------------------
# Tier-2 / Tier-3 fetch helpers (module-level so tests can patch them)
# ---------------------------------------------------------------------------


async def _fetch_primitives(
    instrument: str,
    timeframe: str,
    layers: Optional[list[int]] = None,
    lookback_bars: int = 100,
):
    """Fetch a typed primitives envelope for one (instrument, timeframe).

    On transport failure synthesize a ``not_available`` envelope so the
    framework's Confidence Degradation Rule fires honestly (Phase 47.2.1
    embedded-status pattern).
    """
    from fingpt_core.clients import RetryProfile, VM102Client
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
    )

    layers = layers or [1, 2, 4, 6]
    client = VM102Client(profile=RetryProfile.FAST_FAIL)
    try:
        data = await client.get_primitives_v1(
            instrument=instrument,
            timeframe=timeframe,
            layers=layers,
            lookback_bars=lookback_bars,
        )
        return GetPrimitivesV1Response(**data)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        log.warning(
            "evaluation_runner._fetch_primitives transport-fail %s/%s: %s",
            instrument, timeframe, e,
        )
        return GetPrimitivesV1Response(
            status="not_available",
            data=None,
            meta=NotAvailableMeta(
                planned_phase="VM102 reachable",
                tool="get_primitives",
                would_provide=["layer_bars"],
                impact_on_decision="HIGH",
                unblocks_when=["VM102 backend healthy"],
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "evaluation_runner._fetch_primitives unexpected %s/%s: %s",
            instrument, timeframe, e,
        )
        return GetPrimitivesV1Response(
            status="not_available",
            data=None,
            meta=NotAvailableMeta(
                planned_phase="VM102 healthy",
                tool="get_primitives",
                would_provide=["layer_bars"],
                impact_on_decision="HIGH",
                unblocks_when=["VM102 returns valid envelope"],
            ),
        )
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _fetch_liquidity(
    instrument: str, timeframe: str, lookback_bars: int = 100
):
    """Fetch a typed liquidity envelope for one (instrument, timeframe).

    Synthesizes ``not_available`` on transport / unexpected failure.
    """
    from fingpt_core.clients import RetryProfile, VM102Client
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
    )
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta

    client = VM102Client(profile=RetryProfile.FAST_FAIL)
    try:
        data = await client.get_liquidity(
            instrument=instrument,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
        )
        return GetLiquidityContextResponse(**data)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        log.warning(
            "evaluation_runner._fetch_liquidity transport-fail %s/%s: %s",
            instrument, timeframe, e,
        )
        return GetLiquidityContextResponse(
            status="not_available",
            data=None,
            meta=NotAvailableMeta(
                planned_phase="VM102 reachable",
                tool="get_liquidity_context",
                would_provide=["fvg_zones"],
                impact_on_decision="HIGH",
                unblocks_when=["VM102 backend healthy"],
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "evaluation_runner._fetch_liquidity unexpected %s/%s: %s",
            instrument, timeframe, e,
        )
        return GetLiquidityContextResponse(
            status="not_available",
            data=None,
            meta=NotAvailableMeta(
                planned_phase="VM102 healthy",
                tool="get_liquidity_context",
                would_provide=["fvg_zones"],
                impact_on_decision="HIGH",
                unblocks_when=["VM102 returns valid envelope"],
            ),
        )
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _fetch_news_stub(trade_id: str):
    """Tier-3 stub fetch — V1 always not_available."""
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    return NotAvailableResponse(
        planned_phase="Phase 31",
        tool="get_news_context",
        would_provide=["scheduled_events", "breaking_headlines", "event_proximity"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 31 complete", "News pipeline active"],
    )


async def _fetch_macro_stub(trade_id: str):
    """Tier-3 stub fetch — V1 always not_available."""
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    return NotAvailableResponse(
        planned_phase="Phase 32",
        tool="get_macro_context",
        would_provide=["scheduled_macro", "central_bank_calendar"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 32 complete", "Macro pipeline active"],
    )


# ---------------------------------------------------------------------------
# EvaluationContext builder
# ---------------------------------------------------------------------------


async def _build_eval_context(
    journal_id: str, strategy_id: Optional[str]
) -> EvaluationContext:
    """Phase 47.3 — assemble Tier-1 + Tier-2 + Tier-3 into typed context.

    Tier-2 fetches run via ``asyncio.gather`` (Risk 4 mitigation — cuts
    latency from sequential ~15s to parallel ~3s; preserves the 30s VM100
    timeout headroom).

    Tier-3 stubs are fast (return synthetic ``NotAvailableResponse``
    instantly), so they run sequentially after the gather without latency
    cost.
    """
    tier1 = await build_tier1_context(journal_id)

    # Strategy load — honest gap if YAML missing (CF-5 handled inside Framework)
    strategy = None
    if strategy_id:
        try:
            strategy = load_strategy(strategy_id)
        except Exception as exc:  # noqa: BLE001
            log.info(
                "evaluation_runner: strategy %r unavailable (%s) — "
                "framework will emit no_strategy_warning",
                strategy_id, exc,
            )
            strategy = None

    instrument = tier1.get("instrument") or "UNKNOWN"
    direction = tier1.get("direction") or "neutral"
    journal_md = tier1.get("journal_metadata") or {}
    timeframe = journal_md.get("timeframe") or "M5"

    # Tier-2 — parallel gather. 5 fetches: primitives H1/M15/M5 + liquidity M15/M5.
    prim_h1, prim_m15, prim_m5, liq_m15, liq_m5 = await asyncio.gather(
        _fetch_primitives(instrument, "H1"),
        _fetch_primitives(instrument, "M15"),
        _fetch_primitives(instrument, "M5"),
        _fetch_liquidity(instrument, "M15"),
        _fetch_liquidity(instrument, "M5"),
    )

    # Tier-3 stubs — sequential, fast.
    trade_id = tier1.get("trade_id") or journal_id
    news = await _fetch_news_stub(trade_id)
    macro = await _fetch_macro_stub(trade_id)

    return EvaluationContext(
        journal_id=journal_id,
        instrument=instrument,
        direction=direction,
        strategy_id=strategy_id,
        strategy=strategy,
        timeframe=timeframe,
        entry_price=journal_md.get("entry_price"),
        stop_loss_price=journal_md.get("stop_loss_price"),
        take_profit_price=journal_md.get("take_profit_price"),
        primitives_h1=prim_h1,
        primitives_m15=prim_m15,
        primitives_m5=prim_m5,
        liquidity_m15=liq_m15,
        liquidity_m5=liq_m5,
        macro_context=macro,
        news_context=news,
    )


# ---------------------------------------------------------------------------
# Prompt + LLM helpers
# ---------------------------------------------------------------------------


def _load_system_prompt() -> str:
    abs_path = get_abs_path(PROMPT_PATH)
    return Path(abs_path).read_text(encoding="utf-8")


def _build_framework_block(framework_result: PythonEngineResult) -> str:
    """Render the Python engine's structured output as a JSON block.

    The LLM reads this BEFORE writing narrative fields. The runner discards
    any LLM-supplied values for these fields via ``model_copy`` — this block
    exists so the LLM can CITE the framework outputs in ``reasoning_summary``,
    not so the LLM can challenge them.
    """
    payload = {
        "score": framework_result.score,
        "max_score": framework_result.max_score,
        "recommendation": framework_result.recommendation,
        "confidence_pct": framework_result.confidence_pct,
        "partial_context": framework_result.partial_context,
        "framework_version": framework_result.framework_version,
        "category_results": [
            r.model_dump(mode="json") if hasattr(r, "model_dump") else r
            for r in framework_result.category_results
        ],
        "confidence_adjustments": [
            a.model_dump(mode="json") if hasattr(a, "model_dump") else a
            for a in framework_result.confidence_adjustments
        ],
        "hard_reject_reasons": list(framework_result.hard_reject_reasons),
        "no_strategy_warning": framework_result.no_strategy_warning,
    }
    return json.dumps(payload, indent=2, default=str)


def _build_messages(
    *,
    system_prompt: str,
    schema_json: str,
    framework_block: str,
    journal_id: str,
    context_block: dict,
    history_docs: list[dict],
) -> list[dict]:
    """Construct LLM messages: system + framework block + history + final trigger."""
    rendered_system = system_prompt.replace("{schema_json}", schema_json)
    msgs: list[dict] = [{"role": "system", "content": rendered_system}]

    preamble = (
        f"# Trade Setup Context\n"
        f"- journal_id: {journal_id}\n"
        f"- instrument: {context_block.get('instrument', '<unspecified>')}\n"
        f"- timeframe: {context_block.get('timeframe', '<unspecified>')}\n"
        f"- strategy_id: {context_block.get('strategy_id') or '<none>'}\n"
        f"\n"
        f"## Framework Result\n"
        f"\n"
        f"The deterministic Python rules engine has computed the following.\n"
        f"You MUST NOT modify these fields in your output. Cite specific\n"
        f"category outcomes in your reasoning.\n"
        f"\n"
        f"```json\n{framework_block}\n```\n"
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
        "content": (
            "Generate the formal pre-trade evaluation now. Respond with ONLY "
            "the JSON object. Do NOT modify the Python-owned fields shown in "
            "the Framework Result block."
        ),
    })
    return msgs


async def _call_llm_structured(messages: list[dict], model: str = EVAL_MODEL) -> str:
    """Call LiteLLM JSON mode. Returns the string content from the response.

    Module-level symbol so tests can patch directly:
        patch("core.agents.evaluation_runner._call_llm_structured", new=mock)
    """
    from models import get_api_key  # type: ignore[import]

    service = model.split("/", 1)[0] if "/" in model else model
    api_key = get_api_key(service)

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        api_key=api_key if api_key and api_key != "None" else None,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_pre_trade_evaluation(
    *,
    journal_id: str,
    strategy_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    source_envelope_id: Optional[str] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    db: Any = None,
) -> PreTradeEvaluation:
    """Phase 47.3 framework-first runner.

    Steps (LOCKED):
      1. Build ``EvaluationContext`` (Tier-1 + Tier-2 via gather + Tier-3).
      2. ``Framework().run(ctx)`` → deterministic ``PythonEngineResult``.
      3. Build messages with ``## Framework Result`` block injected.
      4. LLM call (single-shot + ``safe_parse`` retry-once-then-fail).
      5. ``model_copy(update={...})`` — CF-2 OVERWRITE of Python-owned fields.
      6. Persist envelope (Phase 44 lock).

    Args:
        journal_id: TradeJournal UUID (required).
        strategy_id: Optional strategy YAML id.
        conversation_id: Optional Mongo conversation grouping; defaults to journal_id.
        source_envelope_id: Optional explicit source envelope id; otherwise
            resolved from the most-recent agent_zero envelope on this journal.
        task_id: Optional explicit task_id; otherwise auto-generated.
        user_id: Optional caller user id (logged in input_payload).
        db: Optional pymongo db handle; resolved via ``get_mongo_db()`` if None.

    Returns:
        ``PreTradeEvaluation`` with Python-owned fields populated by the
        framework and narrative fields by the LLM.

    Raises:
        EvaluationContractViolation: Both LLM attempts returned PlainTextResult.
            ``envelope_id`` attribute set to the failure envelope's id.
        Exception: LLM hard failure (network, provider error). Failure envelope
            persisted before re-raise.
    """
    task_id = task_id or f"eval-{uuid.uuid4().hex}"
    evaluation_id = str(uuid.uuid4())
    conversation_id = conversation_id or journal_id

    if db is None:
        db = get_mongo_db()

    # ----- Step 1: build EvaluationContext -----
    ctx = await _build_eval_context(journal_id, strategy_id)

    # ----- Step 2: deterministic framework run -----
    framework_result: PythonEngineResult = Framework().run(ctx)

    # ----- Step 3: prepare messages with framework block -----
    cursor = db["agent_envelopes"].find(
        {"journal_id": journal_id, "agent_id": "agent_zero"},
        sort=[("timestamp", 1)],
    )
    history_docs = list(cursor)
    history_docs.sort(key=lambda d: (d or {}).get("timestamp", ""))

    if source_envelope_id is None:
        prev_doc = db["agent_envelopes"].find_one(
            {"journal_id": journal_id, "agent_id": "agent_zero"},
            sort=[("timestamp", -1)],
        )
        source_env_id: Optional[str] = (prev_doc or {}).get("envelope_id")
    else:
        source_env_id = source_envelope_id

    system_prompt = _load_system_prompt()
    schema_json = json.dumps(PreTradeEvaluation.model_json_schema(), indent=2)
    framework_block = _build_framework_block(framework_result)

    context_block = {
        "instrument": ctx.instrument,
        "timeframe": ctx.timeframe,
        "strategy_id": ctx.strategy_id,
    }
    messages = _build_messages(
        system_prompt=system_prompt,
        schema_json=schema_json,
        framework_block=framework_block,
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
        "framework_version": framework_result.framework_version,
    }

    # ----- Step 4: LLM call with retry-once-then-fail -----
    error_chain: list[str] = []
    last_raw: str = ""
    attempt = 0
    parsed: Optional[PreTradeEvaluation] = None

    while attempt < 2:
        attempt += 1
        try:
            raw_content = await _call_llm_structured(messages)
        except Exception as exc:
            log.warning(
                "evaluation LLM hard failure attempt=%d: %s", attempt, exc
            )
            _persist_envelope(
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
            parsed = result  # type: ignore[assignment]
            break

        # PlainTextResult — accumulate error chain, persist degraded envelope.
        error_chain.extend(result.error_chain)
        log.warning(
            "evaluation_runner degraded attempt=%d/2 error_chain=%s",
            attempt, result.error_chain,
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

    if parsed is None:
        # Both attempts degraded — write failure envelope, raise contract violation.
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
        raise EvaluationContractViolation(
            error_chain=error_chain, envelope_id=failure_env_id
        )

    # ===== Step 5: CF-2 ENFORCEMENT =====
    #
    # CRITICAL: This model_copy overwrites ANY value the LLM hallucinated for
    # the Python-owned fields. WITHOUT THIS BLOCK, the LLM silently controls
    # scoring and Phase 47.3's deterministic guarantee is undone.
    #
    # See test_evaluation_runner_47_3.py::test_llm_cannot_override_framework_score
    # for the regression probe. If that test fails, this block is missing or
    # the wrong fields are listed.

    now_utc = datetime.now(timezone.utc)
    risks_with_hard_reject = list(parsed.risks or [])
    for r in framework_result.hard_reject_reasons:
        risks_with_hard_reject.append(f"hard_reject: {r}")
    if framework_result.no_strategy_warning:
        risks_with_hard_reject.append(framework_result.no_strategy_warning)

    evaluation = parsed.model_copy(update={
        # System-injected fields
        "evaluation_id": evaluation_id,
        "trade_id": journal_id,
        "conversation_id": conversation_id,
        "source_envelope_id": source_env_id or "",
        "created_at": now_utc,
        "strategy_id": strategy_id,
        # Tier-1 echo (LLM may not get them right)
        "instrument": ctx.instrument,
        "direction": ctx.direction,
        # === Phase 47.3 — Python-owned fields. LLM-supplied values DISCARDED. ===
        "score": framework_result.score,
        "max_score": framework_result.max_score,
        "recommendation": framework_result.recommendation,
        "confidence": framework_result.confidence_pct / 100.0,
        "category_results": framework_result.category_results,
        "confidence_adjustments": framework_result.confidence_adjustments,
        "partial_context": framework_result.partial_context,
        "framework_version": framework_result.framework_version,
        # Risks: LLM-supplied risks survive + hard_reject reasons appended.
        "risks": risks_with_hard_reject,
    })

    # ----- Step 6: persist success envelope -----
    _persist_envelope(
        db=db,
        task_id=task_id,
        journal_id=journal_id,
        source_env_id=source_env_id,
        status="success",
        input_payload=input_payload,
        output_payload={"evaluation": evaluation.model_dump(mode="json")},
    )

    return evaluation
