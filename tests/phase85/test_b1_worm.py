"""Phase 85 Plan 02 — Task 1 (RED): B1 WORM table constraint tests.

Tests that the agent_reasoning_artifact table:
- Exists in tradetracker_analytics
- Accepts INSERT (all 15 columns)
- Rejects UPDATE (WORM lock)
- Rejects DELETE (WORM lock)

All tests are skipped when POSTGRES_* env vars are not set — CI/dev without
a live analytics DB will skip cleanly. Live tests run in integration env.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.phase_85

# ── skip guard ────────────────────────────────────────────────────────────────

_REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_ANALYTICS_DB")
_all_vars_set = all(os.environ.get(v) for v in _REQUIRED_VARS)

skip_if_no_db = pytest.mark.skipif(
    not _all_vars_set,
    reason="POSTGRES_* env vars not set — skipping live B1 WORM tests",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sample_row() -> dict:
    """Return a dict with all 16 B1 columns for INSERT."""
    return {
        "artifact_id": str(uuid.uuid4()),
        "agent_profile_id": "vm107.macro_release_analyst",
        "sub_profile_id": None,
        "iteration": 1,
        "parent_envelope_id": str(uuid.uuid4()),
        "reasoning_text": "Test reasoning — WORM check.",
        "reasoning_tokens": 10,
        "response_text": "Test response.",
        "response_tokens": 5,
        "tool_called": "lookup_macro_indicator",
        "tool_args": json.dumps({"indicator_id": "CPIAUCSL"}),
        "timestamp": datetime.now(timezone.utc),
        "model_version": "test-model-v1",
        "prompt_version": "test-v0",
        "confidence_self_report": None,
        "citations": json.dumps([]),
    }


INSERT_SQL = """
INSERT INTO agent_reasoning_artifact (
  artifact_id, agent_profile_id, sub_profile_id, iteration, parent_envelope_id,
  reasoning_text, reasoning_tokens, response_text, response_tokens,
  tool_called, tool_args, timestamp, model_version, prompt_version,
  confidence_self_report, citations
) VALUES (
  %(artifact_id)s, %(agent_profile_id)s, %(sub_profile_id)s, %(iteration)s, %(parent_envelope_id)s,
  %(reasoning_text)s, %(reasoning_tokens)s, %(response_text)s, %(response_tokens)s,
  %(tool_called)s, %(tool_args)s, %(timestamp)s, %(model_version)s, %(prompt_version)s,
  %(confidence_self_report)s, %(citations)s
);
"""


# ── tests ─────────────────────────────────────────────────────────────────────

@skip_if_no_db
def test_table_exists():
    """Table agent_reasoning_artifact must exist in tradetracker_analytics."""
    from services.postgres_analytics_client import get_analytics_conn

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'agent_reasoning_artifact'
                """
            )
            count = cur.fetchone()[0]
        assert count == 1, "agent_reasoning_artifact table not found in tradetracker_analytics"
    finally:
        conn.rollback()
        conn.close()


@skip_if_no_db
def test_insert_succeeds():
    """INSERT with all 16 columns succeeds; SELECT returns the same row."""
    from services.postgres_analytics_client import get_analytics_conn

    row = _sample_row()
    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, row)
            cur.execute(
                "SELECT artifact_id FROM agent_reasoning_artifact WHERE artifact_id = %s",
                (row["artifact_id"],)
            )
            result = cur.fetchone()
        conn.commit()
        assert result is not None
        assert str(result[0]) == row["artifact_id"]
    finally:
        # Clean up test row
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agent_reasoning_artifact WHERE artifact_id = %s",
                (row["artifact_id"],)
            )
        conn.commit()
        conn.close()


@skip_if_no_db
def test_update_rejected():
    """UPDATE attempt must fail with InsufficientPrivilege (WORM lock)."""
    import psycopg2
    from services.postgres_analytics_client import get_analytics_conn

    row = _sample_row()
    # First insert a row so we have something to attempt UPDATE on
    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, row)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        pytest.skip("Could not INSERT test row; skipping UPDATE test")
        return

    # Now attempt UPDATE — should be rejected
    update_conn = get_analytics_conn()
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with update_conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_reasoning_artifact SET reasoning_text = 'hax' WHERE artifact_id = %s",
                    (row["artifact_id"],)
                )
            update_conn.commit()
    finally:
        update_conn.rollback()
        update_conn.close()
        # Clean up — owner role or DBA cleanup required in prod
        cleanup_conn = get_analytics_conn()
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_reasoning_artifact WHERE artifact_id = %s",
                    (row["artifact_id"],)
                )
            cleanup_conn.commit()
        except Exception:
            cleanup_conn.rollback()
        finally:
            cleanup_conn.close()


@skip_if_no_db
def test_delete_rejected():
    """DELETE attempt must fail with InsufficientPrivilege (WORM lock)."""
    import psycopg2
    from services.postgres_analytics_client import get_analytics_conn

    row = _sample_row()
    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, row)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        pytest.skip("Could not INSERT test row; skipping DELETE test")
        return
    conn.close()

    delete_conn = get_analytics_conn()
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with delete_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_reasoning_artifact WHERE artifact_id = %s",
                    (row["artifact_id"],)
                )
            delete_conn.commit()
    finally:
        delete_conn.rollback()
        delete_conn.close()
