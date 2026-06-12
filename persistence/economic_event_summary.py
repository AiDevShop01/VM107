"""Phase 85 Plan 09 — VM107 persistence: economic_event ai_executive_summary UPDATE.

Writes the ~50-word Hero Card executive summary composed by the
executive_summary_writer agent (vm107.macro_executive_summary_writer) into the
economic_event.ai_executive_summary column, which was added in Plan 85-03.

Design notes:
- Uses psycopg2 direct (not Django ORM) — consistent with Plan 85-02 B1 pattern.
- Uses get_default_conn() to connect to tradetracker (NOT tradetracker_analytics).
  economic_event lives in tradetracker; using get_analytics_conn() would silently
  match 0 rows (wrong DB — config drift risk).
- Raises RuntimeError on rowcount=0 (D2 lock: silent 0-rows-affected eliminated).
  Two real reasons for rowcount=0: (a) event hasn't replicated yet (degraded),
  (b) wrong DB connection (config drift — would silently skip in tradetracker_analytics).
- Caller manages nothing — connection opened and closed inside write_summary().

Target column (added Plan 85-03):
    ALTER TABLE economic_event ADD COLUMN ai_executive_summary TEXT;
"""
from __future__ import annotations

from services.postgres_analytics_client import get_analytics_conn, get_default_conn

UPDATE_SQL = "UPDATE economic_event SET ai_executive_summary = %s WHERE event_id = %s;"


def write_summary(event_id: str, summary_text: str) -> None:
    """UPDATE economic_event.ai_executive_summary for the given event_id.

    Idempotent: calling twice with the same event_id overwrites the previous value.

    Args:
        event_id: Unique event identifier matching economic_event.event_id
            (e.g. "CPIAUCSL:2026-06-12T12:30:00Z").
        summary_text: The ~50-word executive summary produced by the composer agent.

    Raises:
        RuntimeError: if 0 rows were affected — event_id not found in economic_event.
            Likely causes: (a) event not yet replicated, (b) wrong DB connection
            (economic_event lives in tradetracker via get_default_conn, NOT
            tradetracker_analytics).
        RuntimeError: if any required POSTGRES_* env var is missing (fail-fast).
        psycopg2.Error: on any DB error (callers should handle + retry).
    """
    conn = get_default_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(UPDATE_SQL, (summary_text, event_id))
            if cur.rowcount == 0:
                raise RuntimeError(
                    f"write_summary: 0 rows affected for event_id={event_id!r} — "
                    f"likely wrong DB (economic_event lives in tradetracker via get_default_conn, "
                    f"NOT tradetracker_analytics) or event not yet replicated"
                )
    finally:
        conn.close()
