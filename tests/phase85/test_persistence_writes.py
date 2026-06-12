"""Phase 85 Plan 08a — Task 1 (RED): economic event output table persistence tests.

Tests that:
- economic_event_analysis table accepts UPSERT with all 8 columns; idempotent on retry.
- economic_event_asset_exposure table accepts batch UPSERT with N rows; idempotent
  on retry (ON CONFLICT (event_id, asset_id) DO UPDATE).

All tests are skipped when POSTGRES_* env vars are not set — CI/dev without a
live analytics DB will skip cleanly. Live tests run in integration env.

Tables live in tradetracker_analytics (POSTGRES_ANALYTICS_DB).
Persistence modules: VM107/persistence/economic_event_analysis.py
                     VM107/persistence/economic_event_asset_exposure.py
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

pytestmark = pytest.mark.phase_85

# ── skip guard ────────────────────────────────────────────────────────────────

_REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_ANALYTICS_DB")
_all_vars_set = all(os.environ.get(v) for v in _REQUIRED_VARS)

skip_if_no_db = pytest.mark.skipif(
    not _all_vars_set,
    reason="POSTGRES_* env vars not set — skipping live analytics DB tests",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_event_id() -> str:
    """Return a unique event_id for test isolation."""
    return f"test-event-{uuid.uuid4().hex[:8]}"


def _cleanup_analysis(conn, event_id: str) -> None:
    """Remove test row from economic_event_analysis."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM economic_event_analysis WHERE event_id = %s",
            (event_id,),
        )
    conn.commit()


def _cleanup_exposure(conn, event_id: str) -> None:
    """Remove test rows from economic_event_asset_exposure."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM economic_event_asset_exposure WHERE event_id = %s",
            (event_id,),
        )
    conn.commit()


# ── economic_event_analysis tests ─────────────────────────────────────────────

@skip_if_no_db
def test_economic_event_analysis_upsert_creates_row():
    """upsert() writes one row; SELECT confirms presence and correct column values."""
    from persistence.economic_event_analysis import upsert
    from services.postgres_analytics_client import get_analytics_conn

    event_id = _make_event_id()
    upsert(
        event_id=event_id,
        indicator_id="CPIAUCSL",
        what_happened="CPI came in at 3.4%, above consensus 3.3%.",
        why_it_matters="Inflation persistence may delay Fed rate cuts.",
        regime_impact_label="elevated_inflation",
        citations_json=json.dumps([{"source": "BLS", "snippet": "CPI-U 3.4% YoY"}]),
        envelope_id=None,
    )

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, indicator_id, regime_impact_label
                FROM economic_event_analysis
                WHERE event_id = %s
                """,
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None, "Row not found after upsert"
        assert row[0] == event_id
        assert row[1] == "CPIAUCSL"
        assert row[2] == "elevated_inflation"
    finally:
        _cleanup_analysis(conn, event_id)
        conn.close()


@skip_if_no_db
def test_economic_event_analysis_upsert_idempotent():
    """Calling upsert() twice with same event_id: second call wins; row count stays 1."""
    from persistence.economic_event_analysis import upsert
    from services.postgres_analytics_client import get_analytics_conn

    event_id = _make_event_id()

    # First write
    upsert(
        event_id=event_id,
        indicator_id="CPIAUCSL",
        what_happened="First write — original what_happened text.",
        why_it_matters="Original why_it_matters text.",
        regime_impact_label="elevated_inflation",
        citations_json=None,
        envelope_id=None,
    )

    # Second write — same event_id, updated content
    updated_what = "Second write — updated what_happened text."
    upsert(
        event_id=event_id,
        indicator_id="CPIAUCSL",
        what_happened=updated_what,
        why_it_matters="Updated why_it_matters text.",
        regime_impact_label="high_inflation",
        citations_json=None,
        envelope_id=None,
    )

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), what_happened, regime_impact_label "
                "FROM economic_event_analysis WHERE event_id = %s "
                "GROUP BY what_happened, regime_impact_label",
                (event_id,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)} — UPSERT not idempotent"
        count, what_happened, label = rows[0]
        assert count == 1
        assert what_happened == updated_what, "Second write did not overwrite first"
        assert label == "high_inflation"
    finally:
        _cleanup_analysis(conn, event_id)
        conn.close()


# ── economic_event_asset_exposure tests ───────────────────────────────────────

@skip_if_no_db
def test_economic_event_asset_exposure_batch_insert_creates_n_rows():
    """batch_insert() writes N rows; SELECT confirms all asset_ids present."""
    from persistence.economic_event_asset_exposure import batch_insert
    from services.postgres_analytics_client import get_analytics_conn

    event_id = _make_event_id()
    rows = [
        {"asset_id": "DXY",  "direction": "BULL",    "strength_score": 7, "confidence": 0.82, "rationale": "USD strengthens on hot CPI."},
        {"asset_id": "GOLD", "direction": "BEAR",    "strength_score": 6, "confidence": 0.74, "rationale": "Real rates rise, gold pressured."},
        {"asset_id": "SPX",  "direction": "NEUTRAL", "strength_score": 3, "confidence": 0.51, "rationale": "Mixed: earnings vs rate drag."},
    ]

    batch_insert(event_id=event_id, rows=rows, envelope_id=None)

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asset_id, direction, strength_score "
                "FROM economic_event_asset_exposure WHERE event_id = %s "
                "ORDER BY asset_id",
                (event_id,),
            )
            db_rows = cur.fetchall()
        asset_ids = {r[0] for r in db_rows}
        assert asset_ids == {"DXY", "GOLD", "SPX"}, f"Unexpected asset_ids: {asset_ids}"
        assert len(db_rows) == 3
        # Check DXY row
        dxy = next(r for r in db_rows if r[0] == "DXY")
        assert dxy[1] == "BULL"
        assert dxy[2] == 7
    finally:
        _cleanup_exposure(conn, event_id)
        conn.close()


@skip_if_no_db
def test_economic_event_asset_exposure_unique_constraint_on_event_asset():
    """Second batch_insert with same event_id+asset_id updates in place; no duplicate rows."""
    from persistence.economic_event_asset_exposure import batch_insert
    from services.postgres_analytics_client import get_analytics_conn

    event_id = _make_event_id()
    rows_first = [
        {"asset_id": "DXY",  "direction": "BULL", "strength_score": 6, "confidence": 0.70, "rationale": "Initial assessment."},
    ]
    rows_second = [
        {"asset_id": "DXY",  "direction": "BEAR", "strength_score": 8, "confidence": 0.88, "rationale": "Revised after re-run."},
    ]

    batch_insert(event_id=event_id, rows=rows_first, envelope_id=None)
    batch_insert(event_id=event_id, rows=rows_second, envelope_id=None)

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), direction, strength_score "
                "FROM economic_event_asset_exposure WHERE event_id = %s AND asset_id = 'DXY' "
                "GROUP BY direction, strength_score",
                (event_id,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1, f"Expected 1 row after upsert, got {len(rows)} — duplicate created"
        count, direction, strength = rows[0]
        assert count == 1
        assert direction == "BEAR", "Second batch_insert did not overwrite direction"
        assert strength == 8, "Second batch_insert did not overwrite strength_score"
    finally:
        _cleanup_exposure(conn, event_id)
        conn.close()
