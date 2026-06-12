"""Phase 85 Plan 08a — VM107 persistence: economic_event_analysis UPSERT.

Writes (or updates) one row in the economic_event_analysis table in
tradetracker_analytics.  Called at the end of the release_analyst agent loop
(Plan 85-08b) after generating the what_happened / why_it_matters narrative.

Design notes:
- Uses psycopg2 direct (not Django ORM) — consistent with Plan 85-02 B1 pattern.
- ON CONFLICT (event_id) DO UPDATE ensures agent retries are deterministic (WORM
  NOT applied here — agents may revise their own output on retry).
- citations_json must already be serialised to a JSON string or None.
- envelope_id is the Phase 70.5 envelope UUID linking reasoning chains; optional.
- Caller manages nothing — connection opened and closed inside upsert().
"""
from __future__ import annotations

from services.postgres_analytics_client import get_analytics_conn

UPSERT_SQL = """
INSERT INTO economic_event_analysis (
  event_id, indicator_id, what_happened, why_it_matters, regime_impact_label,
  citations, envelope_id
) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
ON CONFLICT (event_id) DO UPDATE SET
  indicator_id         = EXCLUDED.indicator_id,
  what_happened        = EXCLUDED.what_happened,
  why_it_matters       = EXCLUDED.why_it_matters,
  regime_impact_label  = EXCLUDED.regime_impact_label,
  citations            = EXCLUDED.citations,
  envelope_id          = EXCLUDED.envelope_id;
"""


def upsert(
    event_id: str,
    indicator_id: str,
    what_happened: str,
    why_it_matters: str,
    regime_impact_label: str,
    citations_json: "str | None",
    envelope_id: "str | None",
) -> None:
    """Upsert one row into economic_event_analysis.

    Idempotent: calling twice with the same event_id overwrites the previous
    row (last write wins — correct for agent retries).

    Args:
        event_id: Unique event identifier (e.g. "CPIAUCSL:2026-06-12T12:30:00Z").
        indicator_id: FRED series code (e.g. "CPIAUCSL").
        what_happened: Agent-generated narrative of the release outcome.
        why_it_matters: Agent-generated explanation of macro significance.
        regime_impact_label: One of the indicator's regime threshold labels
            (e.g. "elevated_inflation").
        citations_json: JSON-serialised list of citation dicts, or None.
        envelope_id: Phase 70.5 UUID string linking reasoning chains, or None.

    Raises:
        RuntimeError: if any required POSTGRES_* env var is missing (fail-fast).
        psycopg2.Error: on any DB error (callers should handle + retry).
    """
    conn = get_analytics_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(UPSERT_SQL, (
                event_id,
                indicator_id,
                what_happened,
                why_it_matters,
                regime_impact_label,
                citations_json,
                envelope_id,
            ))
    finally:
        conn.close()
