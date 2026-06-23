"""Phase 90 Plan 06 — macro_forecast_narrator agent.

LLM narrative layer for the Phase 90 4-layer forecast intelligence engine.

LD-90-1 lock at 3 levels:
  Level 1 (Plan 01): ForecastResult.field_validator rejects producer_kind='llm'.
  Level 2 (Plan 01): ExplanationResult is a separate envelope type.
  Level 3 (this module): B5 hard assertion rejects value predictions.

Flow:
  1. Accept ForecastResult-shaped dict (from VM102 Plans 2-5).
  2. Build prompt explaining the model output WITHOUT predicting values.
  3. Call Phase 86 ``services.llm_client.call_llm`` (synchronous).
  4. Hard assertion ``narrator_no_value_prediction``: regex
     ``\\b(will be|will reach|will print)\\b`` — match -> retry ONCE
     with a corrective addendum. If matched again, set
     ``b5_self_eval_passed=False`` and continue (degraded but emitted).
  5. Hard assertion ``narrative_cites_evidence``: regex
     ``\\[ref:(episode|release):<ID>\\]`` — missing -> set
     ``b5_self_eval_passed=False`` (degraded; caller decides).
  6. Return ``ExplanationResult``.

The agent is asynchronous so Plan 06 callers (Phase 85 §11 widget, Phase 89
counterfactual engine) can ``await`` it inside their own async flows, but
the underlying ``call_llm`` is synchronous (Phase 86 pattern) so we wrap it
with ``asyncio.to_thread`` to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Final

from fingpt_core.contracts.explanation_result import ExplanationResult
from services.llm_client import call_llm

# -- Hard-assertion regexes --------------------------------------------------
# Mirror the YAML at registry/agent_profile/vm107.macro_forecast_narrator.yaml.
_VALUE_PREDICTION_RE: Final = re.compile(r"\b(will be|will reach|will print)\b", re.IGNORECASE)
_CITATION_RE: Final = re.compile(r"\[ref:(episode|release):([A-Za-z0-9_-]+)\]")


_SYSTEM_PROMPT_TEMPLATE: Final = (
    "You are a macro forecast narrator. Your ONLY role is to explain what "
    "statistical and ML models have computed. Do NOT predict specific values. "
    "Do NOT say 'will be X%'. Do NOT say 'will reach X'. Do NOT say 'will "
    "print X'. Only describe what the model output means in context. "
    "Always cite evidence: use [ref:episode:ID] or [ref:release:ID] for any "
    "historical fact. You are explaining a {layer} forecast for "
    "{indicator_id}, direction: {direction}, confidence: {direction_confidence}."
)


_CORRECTION_ADDENDUM: Final = (
    "\n\nCORRECTION REQUIRED: Your previous response contained a value "
    "prediction (per LD-90-1, LLMs MUST NOT predict values — that is the "
    "statistical/ML layer's job). Remove the prediction. Describe only the "
    "direction and uncertainty already produced by the model, NOT a specific "
    "numerical value. Re-emit the explanation now."
)


def _build_system_prompt(forecast_result: dict) -> str:
    """Render the system prompt with fields from a ForecastResult-shaped dict."""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        layer=forecast_result.get("layer", "<unknown>"),
        indicator_id=forecast_result.get("indicator_id", "<unknown>"),
        direction=forecast_result.get("direction", "<unknown>"),
        direction_confidence=(
            f"{forecast_result.get('direction_confidence', 0.0):.0%}"
            if isinstance(forecast_result.get("direction_confidence"), (int, float))
            else "<unknown>"
        ),
    )


def _build_user_message(forecast_result: dict, context_text: str = "") -> str:
    """Render the user message describing what the model produced."""
    dist = forecast_result.get("distribution", {}) or {}
    p10 = dist.get("p10")
    p50 = dist.get("p50")
    p90 = dist.get("p90")
    horizon = forecast_result.get("horizon_months")
    producer_model = forecast_result.get("producer_model", "<unknown>")
    indicator_id = forecast_result.get("indicator_id", "<unknown>")
    direction = forecast_result.get("direction", "<unknown>")
    direction_confidence = forecast_result.get("direction_confidence", 0.0)
    feature_attribution = forecast_result.get("feature_attribution") or {}

    parts = [
        f"The {producer_model} model for {indicator_id} forecasts:",
        f"Direction: {direction} with {direction_confidence:.0%} confidence.",
        f"Distribution: p10={p10}, p50={p50}, p90={p90} at {horizon}-month horizon.",
    ]
    if feature_attribution:
        top = sorted(
            ((k, v) for k, v in feature_attribution.items() if isinstance(v, (int, float))),
            key=lambda kv: -abs(kv[1]),
        )[:3]
        if top:
            parts.append(
                "Key drivers: "
                + ", ".join(f"{k} (importance {v:.2f})" for k, v in top)
                + "."
            )
    if context_text:
        parts.append(context_text)
    parts.append(
        "Please provide a 2-3 sentence explanation of what this means. "
        "Cite at least one [ref:episode:ID] or [ref:release:ID]."
    )
    return "\n".join(parts)


def _extract_citations(narrative: str) -> list[str]:
    """Pull every Phase 71 citation token out of the narrative."""
    return [f"{kind}:{cid}" for kind, cid in _CITATION_RE.findall(narrative)]


def _contains_value_prediction(narrative: str) -> bool:
    return bool(_VALUE_PREDICTION_RE.search(narrative))


def _has_citation(narrative: str) -> bool:
    return bool(_CITATION_RE.search(narrative))


def _validate_input(forecast_result: dict) -> None:
    """Lightweight shape check on the input dict (NOT a ForecastResult validate)."""
    required = ("indicator_id", "layer", "distribution", "direction")
    missing = [k for k in required if k not in forecast_result]
    if missing:
        raise KeyError(
            "macro_forecast_narrator_agent input missing keys: "
            f"{missing}; expected ForecastResult-shaped dict"
        )


async def _call_llm_async(prompt: str) -> str:
    """Run the synchronous call_llm in a thread so we don't block the loop."""
    return await asyncio.to_thread(call_llm, prompt)


async def macro_forecast_narrator_agent(
    forecast_result: dict,
    context_text: str = "",
) -> ExplanationResult:
    """Emit an ExplanationResult narrating a ForecastResult-shaped dict.

    Args:
        forecast_result: ForecastResult-shaped dict from VM102 Plans 2-5.
            MUST carry ``indicator_id``, ``layer``, ``distribution``,
            ``direction``. Not coerced through ``ForecastResult.model_validate``
            here — Plan 06's contract is "consume what the producer emitted"
            so we tolerate harmless extras.
        context_text: Optional caller-supplied context (e.g. "this run was
            triggered by the 2026-03 CPI release").

    Returns:
        ``ExplanationResult`` envelope. ``producer_kind`` is always ``"llm"``
        (allowed on ExplanationResult, forbidden on ForecastResult per
        LD-90-1). ``b5_self_eval_passed`` is False when either hard
        assertion fails after a retry; otherwise True.

    Raises:
        KeyError: input dict missing required ForecastResult-shape keys.
    """
    _validate_input(forecast_result)

    system_prompt = _build_system_prompt(forecast_result)
    user_message = _build_user_message(forecast_result, context_text=context_text)
    base_prompt = f"{system_prompt}\n\n{user_message}"

    narrative = await _call_llm_async(base_prompt)

    b5_passed = True

    # Hard assertion 1 — narrator_no_value_prediction.
    if _contains_value_prediction(narrative):
        corrective_prompt = base_prompt + _CORRECTION_ADDENDUM
        narrative = await _call_llm_async(corrective_prompt)
        if _contains_value_prediction(narrative):
            # Value prediction survived the retry — degraded.
            b5_passed = False

    # Hard assertion 2 — narrative_cites_evidence.
    if not _has_citation(narrative):
        b5_passed = False

    return ExplanationResult(
        indicator_id=forecast_result["indicator_id"],
        explanation_text=narrative,
        producer_kind="llm",
        generated_at=datetime.now(timezone.utc),
        b5_self_eval_passed=b5_passed,
        phase71_citations=_extract_citations(narrative),
    )
