"""Phase 85 / 85.1 — Backfill CLI harness for EconomicIndicator.ai_description.

Phase 85 Plan 15 originally shipped this file using a broken ``run_agent``
callsite that does not exist (AttributeError).  Phase 85.1 Plan 04 rewrites
the agent dispatch to use the canonical path introduced in Plan 02:

    _dispatch_agent_sync (VM107.workers.agent_invocation)
    parse_and_persist    (VM107.workers.output_routing)

This keeps backfill and the live task dispatcher on ONE invocation path with a
single failure surface.  RESEARCH.md "Don't Hand-Roll" row 6 + "Recommendation:
backfill agent should be invoked via the SAME dispatcher" note.

Usage:
    python -m VM107.backfill.backfill_indicator_descriptions --all
    python -m VM107.backfill.backfill_indicator_descriptions --indicator CPIAUCSL
    python -m VM107.backfill.backfill_indicator_descriptions --all --limit 10
    python -m VM107.backfill.backfill_indicator_descriptions --all --dry-run

CLI flags:
    --all          Iterate all pending indicators (NULL or non-manual-override)
    --indicator    Single indicator code (e.g. CPIAUCSL)
    --limit N      Process at most N indicators (default: no limit)
    --dry-run      Print what would be dispatched without calling the agent

Idempotent:
    - Rows with manual_override=true in ai_description are ALWAYS skipped.
      Admin-curated descriptions must not be overwritten by LLM backfill.
    - Non-locked rows may be re-described on repeated --all runs.

Option B (Dagster asset macro_indicator_descriptions partitioned by
indicator_code × prompt_version) is DEFERRED to Phase 86.
See 85.1-04-SUMMARY.md for deferral rationale.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical agent invocation + output routing (Plan 02 deliverables).
# These MUST be module-level attributes so tests can patch them via:
#   patch("backfill.backfill_indicator_descriptions._dispatch_agent_sync", mock)
#   patch("backfill.backfill_indicator_descriptions.parse_and_persist", mock)
# ---------------------------------------------------------------------------
from workers.agent_invocation import _dispatch_agent_sync
from workers.output_routing import parse_and_persist

logger = logging.getLogger("backfill_indicator_descriptions")

PROMPT_VERSION = os.environ.get("VM107_DESCRIBER_PROMPT_VERSION", "v1")


# ---------------------------------------------------------------------------
# Direct LLM dispatch (Phase 86-10 UAT hot-patch)
# ---------------------------------------------------------------------------
#
# The original Agent Zero dispatch path (`_dispatch_agent_sync` → `/api/api_message`)
# corrupted itself after 2-3 successive calls during Phase 86-10 UAT:
#   - AAA + ANFCI wrote cleanly (HTTP 200, valid envelopes)
#   - BAA onwards: `ValueError: Tool request must have a tool_name (type string)`
#     from the agent's tool-call validation. The agent's response (clean JSON)
#     was being interpreted as an attempted tool call and rejected.
#   - Agent then thrashes through reprompt-once retries and never completes.
#
# Editorial description generation does not need Agent Zero's full agent runtime
# (no tools, no subordinates, no memory). It needs a prompt + an LLM call. The
# direct dispatch path below skips A0 entirely:
#   1. Load the system prompt from the agent's existing prompt file (so the
#      contract stays identical and admin override compatibility is preserved).
#   2. Build the user message using the same _build_describer_message logic.
#   3. Call the configured model (CHAT_MODEL env var, defaults to deepseek-chat)
#      via litellm. Each call is stateless — no shared conversation state.
#   4. Return the raw response text + a telemetry dict shaped like the A0 path
#      so parse_and_persist downstream is unchanged.
#
# A0 path is intentionally kept available for tests + the existing
# macro_release_analyst / macro_executive_summary_writer profiles which require
# Agent Zero's tool ecosystem.

_PROMPT_FILE_DEFAULT = Path(__file__).resolve().parent.parent / "prompts" / "macro_indicator_describer.md"


def _load_system_prompt(prompt_path: Path = _PROMPT_FILE_DEFAULT) -> str:
    """Load the macro_indicator_describer system prompt from disk."""
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Describer system prompt not found at {prompt_path}. "
            "Phase 85-15 should have shipped this file; check VM107/prompts/."
        )
    return prompt_path.read_text()


def _dispatch_describer_direct(indicator: dict) -> tuple[str, dict]:
    """Direct LLM dispatch — bypasses Agent Zero.

    Returns (raw_response_text, telemetry_dict) — same shape as
    _dispatch_agent_sync so parse_and_persist downstream is unchanged.

    Model selection:
        Uses CHAT_MODEL env var (set by A0 startup), defaults to
        ``deepseek/deepseek-chat`` which is configured for the local stack and
        has good JSON-mode support. Override via DESCRIBER_MODEL env var.

    Raises:
        RuntimeError: if API_KEY_DEEPSEEK (or the resolved provider's key) is
                      unset — fail-fast, no fallback default key.
    """
    import litellm  # local import — keep module-load fast for tests that mock this

    code = indicator.get("indicator_id", "UNKNOWN")
    system_prompt = _load_system_prompt()
    user_message = _build_describer_message(indicator)

    model = os.environ.get("DESCRIBER_MODEL") or os.environ.get(
        "CHAT_MODEL", "deepseek/deepseek-chat"
    )

    # Fail-fast on missing API key (Phase 47.3 env-driven-no-fallbacks lock).
    # Provider→env-var name follows the API_KEY_<PROVIDER> convention used by A0.
    provider = model.split("/")[0].upper() if "/" in model else "DEEPSEEK"
    api_key_env = f"API_KEY_{provider}"
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(
            f"{api_key_env} env var REQUIRED for direct dispatch (model={model}). "
            "Set it in /a0/usr/.env or pass DESCRIBER_MODEL to use a provider whose key is set."
        )

    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=800,
        temperature=0.2,
        api_key=api_key,
    )

    raw = response.choices[0].message.content or ""
    telemetry = {
        "model_used": getattr(response, "model", model),
        "reason_chain": [],
        "cost": {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
            "completion_tokens": getattr(response.usage, "completion_tokens", 0),
            "total_tokens": getattr(response.usage, "total_tokens", 0),
        },
        "fallback_used": False,
        "b1_artifact_id": None,
        "context_id": None,
    }
    return raw, telemetry


# ---------------------------------------------------------------------------
# Indicator fetch
# ---------------------------------------------------------------------------

def fetch_indicators_for_backfill(
    only_indicator: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """Load indicators that need AI descriptions from ref_economic_indicators.

    Returns a list of dicts with keys:
        indicator_id, indicator_name, formula, components,
        importance, source_agency_code, frequency, is_manual_override.

    Filtering:
        - If only_indicator is set, returns that single row regardless of status.
        - Otherwise: rows where ai_description IS NULL OR
          (ai_description->>'manual_override')::bool IS NOT TRUE.
          This means: unset rows + agent-generated rows (not human-locked).
        - manual_override rows are INCLUDED in the fetch result (with
          is_manual_override=True) so the caller can log the skip count.

    Args:
        only_indicator: Fetch only this indicator_code (for --indicator flag).
        limit: Maximum number of rows to return (applied after ORDER BY).
    """
    from services.postgres_analytics_client import get_default_conn

    with get_default_conn() as conn:
        with conn.cursor() as cur:
            if only_indicator:
                cur.execute(
                    "SELECT indicator_code, indicator_name, formula, components, "
                    "importance, source_agency_code, frequency, "
                    "(ai_description->>'manual_override')::bool AS is_manual_override "
                    "FROM ref_economic_indicators "
                    "WHERE indicator_code = %s",
                    (only_indicator,),
                )
            else:
                limit_clause = f"LIMIT {int(limit)}" if limit else ""
                cur.execute(
                    "SELECT indicator_code, indicator_name, formula, components, "
                    "importance, source_agency_code, frequency, "
                    "(ai_description->>'manual_override')::bool AS is_manual_override "
                    "FROM ref_economic_indicators "
                    "WHERE ai_description IS NULL "
                    "   OR (ai_description->>'manual_override')::bool IS NOT TRUE "
                    f"ORDER BY indicator_code {limit_clause}"
                )
            rows = cur.fetchall()

    cols = [
        "indicator_id", "indicator_name", "formula", "components",
        "importance", "source_agency_code", "frequency", "is_manual_override",
    ]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def _build_describer_message(indicator: dict) -> str:
    """Build the natural-language prompt sent to vm107.macro_indicator_describer.

    Mirrors the original Phase 85-15 prompt shape — a single string with the
    indicator metadata and a request for strict JSON output with three fields.

    Args:
        indicator: Dict from fetch_indicators_for_backfill — must contain at
                   minimum 'indicator_code'.
    """
    code = indicator.get("indicator_id", "UNKNOWN")
    name = indicator.get("indicator_name") or code
    formula = indicator.get("formula") or ""
    components = indicator.get("components") or []
    importance = indicator.get("importance") or "MED"
    publisher = indicator.get("source_agency_code") or "FRED"
    schedule = indicator.get("frequency") or ""

    components_str = json.dumps(components) if components else "[]"

    return (
        f"You are vm107.macro_indicator_describer.\n"
        f"Describe the following economic indicator for use on the IndicatorPage.\n\n"
        f"Indicator code: {code}\n"
        f"Title: {name}\n"
        f"Formula / methodology: {formula}\n"
        f"Components: {components_str}\n"
        f"Importance tier: {importance}\n"
        f"Publishing agency: {publisher}\n"
        f"Release schedule: {schedule}\n\n"
        f"Return ONLY strict JSON with exactly these keys:\n"
        f"  what_is_it       (str, max 240 chars)\n"
        f"  why_important    (str, max 360 chars)\n"
        f"  why_traders_care (str, max 360 chars)\n"
    )


# ---------------------------------------------------------------------------
# Agent dispatch — canonical path (Plan 02)
# ---------------------------------------------------------------------------

def _dispatch_describer(indicator: dict, prompt_version: str = PROMPT_VERSION) -> str:
    """Invoke macro_indicator_describer for one indicator. Returns envelope_id.

    Uses _dispatch_agent_sync + parse_and_persist — THE SAME PATH used by the
    live task dispatcher (Plan 02).  There is no second invocation path in this
    codebase.

    The previous ``_dispatch_agent()`` function using the broken ``run_agent``
    callsite has been removed.  It raised AttributeError at runtime
    (Phase 85 UAT bug PHASE85.1-REQ-2).

    Args:
        indicator: Dict from fetch_indicators_for_backfill.
        prompt_version: Semver string stored in goal_payload for audit trail.

    Returns:
        envelope_id (str) from parse_and_persist.

    Raises:
        Any exception from _dispatch_agent_sync or parse_and_persist propagates
        to the caller.  The main loop logs-and-continues so a single bad
        indicator does not abort the batch.
    """
    code = indicator["indicator_id"]
    # Phase 86-10 UAT hot-patch: bypass Agent Zero (broken after 2-3 calls,
    # see _dispatch_describer_direct docstring). The A0 path is preserved via
    # the BACKFILL_USE_AGENT_ZERO env var for tests + future profile recovery.
    if os.environ.get("BACKFILL_USE_AGENT_ZERO", "0") == "1":
        message = _build_describer_message(indicator)
        raw, telemetry = _dispatch_agent_sync("vm107.macro_indicator_describer", message)
    else:
        raw, telemetry = _dispatch_describer_direct(indicator)
    envelope_id = parse_and_persist(
        "vm107.macro_indicator_describer",
        raw,
        telemetry,
        goal_payload={
            "indicator_id": code,   # parse_and_persist uses "indicator_id" key
            "prompt_version": prompt_version,
        },
    )
    return envelope_id


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(
    only_indicator: Optional[str] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> None:
    """Execute the backfill for pending indicators.

    Args:
        only_indicator: If set, process only this indicator code.
        dry_run: If True, log what would be dispatched without calling the agent.
        limit: Maximum number of indicators to process.
    """
    indicators = fetch_indicators_for_backfill(only_indicator=only_indicator, limit=limit)

    logger.info(
        f"backfill_indicator_descriptions: {len(indicators)} indicators fetched "
        f"(dry_run={dry_run}, limit={limit})"
    )

    wrote = 0
    skipped_manual = 0
    errors = 0

    for indicator in indicators:
        code = indicator["indicator_id"]
        is_manual = bool(indicator.get("is_manual_override"))

        if is_manual:
            skipped_manual += 1
            logger.info(f"{code}: SKIPPED (manual_override=true — admin-curated description locked)")
            continue

        if dry_run:
            logger.info(f"DRY RUN: would dispatch vm107.macro_indicator_describer for {code!r}")
            continue

        try:
            envelope_id = _dispatch_describer(indicator)
            wrote += 1
            logger.info(f"{code}: WROTE description (envelope_id={envelope_id})")
        except Exception as exc:
            errors += 1
            logger.error(f"{code}: ERROR — {exc}", exc_info=True)

    logger.info(
        f"backfill_indicator_descriptions complete: "
        f"ok={wrote}, skipped_manual_override={skipped_manual}, errors={errors}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(
    limit: Optional[int] = None,
    indicator: Optional[str] = None,
    dry_run: bool = False,
    all_indicators: bool = False,
    _argv: Optional[list[str]] = None,
) -> None:
    """CLI entry point. Accepts both programmatic kwargs and sys.argv.

    Programmatic usage (e.g. from tests or Dagster ops):
        main(limit=10)
        main(indicator="CPIAUCSL")
        main(all_indicators=True, dry_run=True)

    CLI usage:
        python -m VM107.backfill.backfill_indicator_descriptions --all --limit 10

    Args:
        limit: Process at most this many indicators (overrides --limit).
        indicator: Single indicator code (overrides --indicator).
        dry_run: Do not call the agent (overrides --dry-run).
        all_indicators: Process all pending indicators (overrides --all).
        _argv: If provided, parse this list instead of sys.argv (for testing).
    """
    # Only parse CLI args if called as a script (no programmatic kwargs supplied).
    _programmatic = (
        limit is not None
        or indicator is not None
        or dry_run
        or all_indicators
    )

    if not _programmatic:
        p = argparse.ArgumentParser(
            description="Backfill EconomicIndicator.ai_description via macro_indicator_describer agent."
        )
        p.add_argument("--indicator", help="Single indicator code (e.g. CPIAUCSL)")
        p.add_argument(
            "--all",
            dest="all_indicators",
            action="store_true",
            help="Process all pending indicators",
        )
        p.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of indicators to process",
        )
        p.add_argument("--dry-run", action="store_true", help="Log diffs without calling the agent")

        args = p.parse_args(_argv)

        if not args.all_indicators and not args.indicator:
            p.error("Specify --all or --indicator <code>")

        indicator = args.indicator
        all_indicators = args.all_indicators
        limit = args.limit
        dry_run = args.dry_run

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(message)s",
    )

    run(
        only_indicator=indicator,
        dry_run=dry_run,
        limit=limit,
    )


if __name__ == "__main__":
    main()
