"""Phase 85 Plan 08a — VM107 persistence: economic_event_asset_exposure batch UPSERT.

Writes (or updates) N rows in the economic_event_asset_exposure table in
tradetracker_analytics.  Called at the end of the asset_exposure_analyst agent loop
(Plan 85-08b) after scoring each paired asset for the released event.

Design notes:
- Uses psycopg2 direct + execute_values for efficient batch insert.
- ON CONFLICT (event_id, asset_id) DO UPDATE ensures agent retries are
  deterministic: re-running the asset_exposure_analyst for the same event
  overwrites prior scores rather than creating duplicates.
- direction values: "BULL" | "BEAR" | "NEUTRAL" — enforced by agent profile,
  not by DB constraint.
- strength_score coerced to int; confidence coerced to float defensively.
- Caller manages nothing — connection opened and closed inside batch_insert().
"""
from __future__ import annotations

from typing import Any

from services.postgres_analytics_client import get_analytics_conn

BATCH_UPSERT_SQL = """
INSERT INTO economic_event_asset_exposure (
  event_id, asset_id, direction, strength_score, confidence, rationale, envelope_id
) VALUES %s
ON CONFLICT (event_id, asset_id) DO UPDATE SET
  direction      = EXCLUDED.direction,
  strength_score = EXCLUDED.strength_score,
  confidence     = EXCLUDED.confidence,
  rationale      = EXCLUDED.rationale,
  envelope_id    = EXCLUDED.envelope_id;
"""


def batch_insert(
    event_id: str,
    rows: "list[dict[str, Any]]",
    envelope_id: "str | None",
) -> None:
    """Batch-upsert N asset exposure rows for one event.

    Idempotent: calling twice with the same event_id + asset_id pairs overwrites
    prior scores (last write wins — correct for agent retries).

    Args:
        event_id: Unique event identifier (matches economic_event_analysis.event_id).
        rows: List of dicts, each containing:
            - asset_id (str): e.g. "DXY", "GOLD", "SPX"
            - direction (str): "BULL" | "BEAR" | "NEUTRAL"
            - strength_score (int | float): coerced to int; expected 1–10
            - confidence (float): coerced to float; expected 0.0–1.0
            - rationale (str, optional): agent rationale text; defaults to None
        envelope_id: Phase 70.5 UUID string linking reasoning chains, or None.

    Raises:
        RuntimeError: if any required POSTGRES_* env var is missing (fail-fast).
        psycopg2.Error: on any DB error (callers should handle + retry).
    """
    from psycopg2.extras import execute_values

    values = [
        (
            event_id,
            r["asset_id"],
            r["direction"],
            int(r["strength_score"]),
            float(r["confidence"]),
            r.get("rationale"),
            envelope_id,
        )
        for r in rows
    ]
    conn = get_analytics_conn()
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, BATCH_UPSERT_SQL, values)
    finally:
        conn.close()
