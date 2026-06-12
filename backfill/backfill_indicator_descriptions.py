"""Phase 85 Plan 15 — Backfill CLI harness for EconomicIndicator.ai_description.

Invokes vm107.macro_indicator_describer agent once per indicator and persists
the output to EconomicIndicator.ai_description JSONB column.

Usage:
    python -m backfill.backfill_indicator_descriptions --all
    python -m backfill.backfill_indicator_descriptions --indicator CPIAUCSL
    python -m backfill.backfill_indicator_descriptions --all --dry-run

CLI flags:
    --all          Iterate all pending indicators (NULL or non-manual-override)
    --indicator    Single indicator code (e.g. CPIAUCSL)
    --dry-run      Print diffs without writing (no DB changes)

Idempotent:
    - Rows already backfilled (non-null, non-manual-override) are re-described
      on --all (idempotency via the upsert helper skipping manual_override=true).
    - Rows with manual_override=true are always skipped (locked by admin POST).

Design: one-shot CLI, not a listener. Intended to be run at:
    1. Launch time (initial population of all 64 indicators)
    2. On prompt-version bump (re-describe all non-locked rows)
    3. On --indicator for spot updates

Note on dispatch: uses _dispatch_agent() — a thin sync wrapper around the
asyncio agent loop. Tests mock this function; production callers may swap it for
a full async path. See _dispatch_agent() docstring for the contract.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional

from persistence.economic_indicator_description import upsert_description
from services.postgres_analytics_client import get_default_conn

logger = logging.getLogger("backfill_indicator_descriptions")

PROMPT_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────────────────────
# Agent dispatch abstraction
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_agent(input_payload: dict) -> dict:
    """Dispatch macro_indicator_describer agent with input_payload.

    Returns a dict with keys:
        what_is_it, why_important, why_traders_care  — agent output fields
        _model_version — string, e.g. "claude-3-5-sonnet-20241022"
        _prompt_version — string, e.g. "1.0.0"

    In production this wraps the async agent loop via asyncio.run().
    In tests this function is mocked via patch().

    The Phase 36 AgentRunner API is async; we use asyncio.run() for one-shot
    CLI use (not a concern for the listener-based agents which already run
    inside an event loop).

    If the agent runtime is not available (e.g. REDIS_URL unset), the
    RuntimeError propagates to the caller — the backfill halts on that indicator
    and logs the error. This is intentional: partial backfill with logged errors
    is preferable to silently skipping indicators.
    """
    try:
        # Lazy import — agent infrastructure may not be available in test environments
        from agents._router_reachability import assert_router_reachable
        assert_router_reachable()

        # Import the Phase 36 AgentRunner async path
        import agent as agent_module

        async def _run():
            # Build a minimal task string for the describer
            task_text = (
                f"Describe the following economic indicator:\n"
                f"{input_payload}"
            )
            result = await agent_module.run_agent(
                profile_id="vm107.macro_indicator_describer",
                task=task_text,
                context=input_payload,
            )
            return result

        result = asyncio.run(_run())
        return {
            "what_is_it": result.get("what_is_it", ""),
            "why_important": result.get("why_important", ""),
            "why_traders_care": result.get("why_traders_care", ""),
            "_model_version": result.get("model_version", "unknown"),
            "_prompt_version": PROMPT_VERSION,
        }
    except Exception as exc:
        logger.error(
            f"_dispatch_agent failed for indicator {input_payload.get('indicator_code')!r}: {exc}",
            exc_info=True,
        )
        raise


# ─────────────────────────────────────────────────────────────────────────────
# DB queries
# ─────────────────────────────────────────────────────────────────────────────

def load_pending_indicators(only_indicator: Optional[str] = None) -> list[tuple]:
    """Load indicator rows that need description.

    Returns list of tuples:
        (indicator_code, indicator_name, formula, components, importance, source_agency_code, frequency)

    Filtering:
        - If only_indicator is set, returns that single row regardless of status.
        - Otherwise: rows where ai_description IS NULL OR
          (ai_description->>'manual_override')::bool IS NOT TRUE
          This means: unset rows + agent-generated rows (not human-locked).
    """
    with get_default_conn() as conn:
        with conn.cursor() as cur:
            if only_indicator:
                cur.execute(
                    "SELECT indicator_code, indicator_name, formula, components, "
                    "importance, source_agency_code, frequency "
                    "FROM ref_economic_indicators "
                    "WHERE indicator_code = %s",
                    (only_indicator,),
                )
            else:
                cur.execute(
                    "SELECT indicator_code, indicator_name, formula, components, "
                    "importance, source_agency_code, frequency "
                    "FROM ref_economic_indicators "
                    "WHERE ai_description IS NULL "
                    "   OR (ai_description->>'manual_override')::bool IS NOT TRUE"
                )
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

def run(only_indicator: Optional[str] = None, dry_run: bool = False) -> None:
    """Execute the backfill for pending indicators.

    Args:
        only_indicator: If set, process only this indicator code.
        dry_run: If True, log what would be done without writing to DB.
    """
    rows = load_pending_indicators(only_indicator)
    logger.info(
        f"backfill_indicator_descriptions: {len(rows)} indicators to process "
        f"(dry_run={dry_run})"
    )

    wrote = 0
    skipped = 0
    errors = 0

    for row in rows:
        (code, name, formula, components, importance, publisher, schedule) = row
        input_payload = {
            "indicator_code": code,
            "title": name or code,
            "formula": formula or "",
            "components": components or [],
            "importance": importance or "MED",
            "publisher": publisher or "FRED",
            "schedule": schedule or "",
        }

        if dry_run:
            logger.info(f"DRY RUN: would describe {code!r} (title={name!r})")
            continue

        try:
            desc = _dispatch_agent(input_payload)
            written = upsert_description(
                code,
                {
                    "what_is_it": desc["what_is_it"],
                    "why_important": desc["why_important"],
                    "why_traders_care": desc["why_traders_care"],
                },
                model_version=desc.get("_model_version", "unknown"),
                prompt_version=PROMPT_VERSION,
                manual_override=False,
            )
            if written:
                wrote += 1
                logger.info(f"{code}: WROTE description")
            else:
                skipped += 1
                logger.info(f"{code}: SKIPPED (manual_override=true)")
        except Exception as exc:
            errors += 1
            logger.error(f"{code}: ERROR — {exc}")

    logger.info(
        f"backfill_indicator_descriptions complete: "
        f"wrote={wrote}, skipped={skipped}, errors={errors}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser(
        description="Backfill EconomicIndicator.ai_description via macro_indicator_describer agent."
    )
    p.add_argument("--indicator", help="Single indicator code (e.g. CPIAUCSL)")
    p.add_argument("--all", dest="all_indicators", action="store_true", help="Process all pending indicators")
    p.add_argument("--dry-run", action="store_true", help="Log diffs without writing to DB")

    args = p.parse_args()

    if not args.all_indicators and not args.indicator:
        p.error("Specify --all or --indicator <code>")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(message)s",
    )

    run(
        only_indicator=args.indicator,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
