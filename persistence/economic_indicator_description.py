"""Phase 85 Plan 15 — Persistence helper for EconomicIndicator.ai_description.

Provides upsert_description() which writes the agent-generated description JSON
to the ref_economic_indicators table via psycopg2 (tradetracker DB).

Key behaviours:
- Skips rows where existing ai_description->>'manual_override' is true
  (manual override locks the row from re-backfill).
- Returns True if the UPDATE was executed, False if skipped.
- Uses get_default_conn() from Plan 85-01 (tradetracker DB, not analytics).
- Idempotent: calling twice on the same indicator overwrites unless locked.

Caller (backfill_indicator_descriptions.py) is responsible for commit/rollback
handling. psycopg2 connections are managed via context manager in this module.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from services.postgres_analytics_client import get_default_conn


def upsert_description(
    indicator_code: str,
    description_dict: dict,
    *,
    model_version: str,
    prompt_version: str,
    manual_override: bool = False,
) -> bool:
    """Upsert EconomicIndicator.ai_description JSONB for the given indicator_code.

    Args:
        indicator_code: Primary key of ref_economic_indicators (e.g. "CPIAUCSL").
        description_dict: Dict with keys what_is_it, why_important, why_traders_care.
        model_version: LLM model identifier (e.g. "claude-3-5-sonnet-20241022").
        prompt_version: Prompt semver string (e.g. "1.0.0").
        manual_override: If True, force-write even if existing row has manual_override=True.
            Used by the admin POST route (Plan 85-15 Task 3).

    Returns:
        True if the UPDATE was executed (write happened).
        False if skipped because the existing row has manual_override=True
            and we were NOT called with manual_override=True.
    """
    payload = {
        **description_dict,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": model_version,
        "prompt_version": prompt_version,
        "manual_override": manual_override,
    }
    with get_default_conn() as conn:
        with conn.cursor() as cur:
            # Check whether existing row has manual_override=true.
            # If it does and we're not a manual override call, skip.
            cur.execute(
                "SELECT (ai_description->>'manual_override')::bool "
                "FROM ref_economic_indicators "
                "WHERE indicator_code = %s",
                (indicator_code,),
            )
            row = cur.fetchone()
            if row and row[0] is True and not manual_override:
                return False

            cur.execute(
                "UPDATE ref_economic_indicators "
                "SET ai_description = %s "
                "WHERE indicator_code = %s",
                (json.dumps(payload), indicator_code),
            )
            conn.commit()
            return True
