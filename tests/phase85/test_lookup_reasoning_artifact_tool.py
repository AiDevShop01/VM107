"""Phase 85 Plan 02 — Task 2 (RED): lookup_reasoning_artifact tool tests.

Tests:
- Raises RuntimeError when no filter provided
- Returns rows by artifact_id (live DB, skipped when no POSTGRES_*)
- Returns rows by profile+time range, correctly ordered + counted
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.phase_85

# ── skip guard ────────────────────────────────────────────────────────────────

_REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_ANALYTICS_DB")
_all_vars_set = all(os.environ.get(v) for v in _REQUIRED_VARS)

skip_if_no_db = pytest.mark.skipif(
    not _all_vars_set,
    reason="POSTGRES_* env vars not set — skipping live lookup_reasoning_artifact tests",
)

# ── helpers ───────────────────────────────────────────────────────────────────

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

CLEANUP_SQL = "DELETE FROM agent_reasoning_artifact WHERE agent_profile_id = %s;"


def _fixture_row(profile_id: str, ts: datetime, iteration: int = 1) -> dict:
    return {
        "artifact_id": str(uuid.uuid4()),
        "agent_profile_id": profile_id,
        "sub_profile_id": None,
        "iteration": iteration,
        "parent_envelope_id": None,
        "reasoning_text": f"Test reasoning iter={iteration}",
        "reasoning_tokens": 10,
        "response_text": f"Test response iter={iteration}",
        "response_tokens": 5,
        "tool_called": None,
        "tool_args": None,
        "timestamp": ts,
        "model_version": "test-model",
        "prompt_version": "test-v0",
        "confidence_self_report": None,
        "citations": json.dumps([]),
    }


# ── tests ─────────────────────────────────────────────────────────────────────

def test_raises_when_no_filter():
    """RuntimeError raised when neither artifact_id nor agent_profile_id provided."""
    from tools.lookup_reasoning_artifact import lookup_reasoning_artifact

    with pytest.raises(RuntimeError, match="artifact_id or agent_profile_id"):
        lookup_reasoning_artifact()


@skip_if_no_db
def test_lookup_by_id():
    """Insert a fixture row; lookup by artifact_id returns single row with all fields."""
    from services.postgres_analytics_client import get_analytics_conn
    from tools.lookup_reasoning_artifact import lookup_reasoning_artifact

    row = _fixture_row("vm107.macro_test_profile", datetime.now(timezone.utc))
    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, row)
        conn.commit()
    finally:
        conn.close()

    try:
        result = lookup_reasoning_artifact(artifact_id=row["artifact_id"])
        assert len(result) == 1
        r = result[0]
        assert str(r["artifact_id"]) == row["artifact_id"]
        assert r["agent_profile_id"] == "vm107.macro_test_profile"
        assert r["reasoning_text"] == row["reasoning_text"]
        assert r["response_text"] == row["response_text"]
        # All 15+ fields present
        for field in ("artifact_id", "agent_profile_id", "iteration", "reasoning_text",
                      "response_text", "tool_called", "timestamp", "model_version",
                      "prompt_version", "confidence_self_report", "citations"):
            assert field in r, f"Missing field: {field}"
    finally:
        cleanup_conn = get_analytics_conn()
        with cleanup_conn.cursor() as cur:
            cur.execute(CLEANUP_SQL, ("vm107.macro_test_profile",))
        cleanup_conn.commit()
        cleanup_conn.close()


@skip_if_no_db
def test_lookup_by_profile_time_range():
    """Insert 3 rows across time; query with since/until/limit returns correct ordering."""
    from services.postgres_analytics_client import get_analytics_conn
    from tools.lookup_reasoning_artifact import lookup_reasoning_artifact

    profile_id = "vm107.macro_timerange_test"
    base_ts = datetime.now(timezone.utc) - timedelta(hours=3)
    rows = [
        _fixture_row(profile_id, base_ts + timedelta(hours=i), iteration=i + 1)
        for i in range(3)
    ]

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(INSERT_SQL, r)
        conn.commit()
    finally:
        conn.close()

    try:
        since = base_ts - timedelta(minutes=1)
        until = base_ts + timedelta(hours=4)
        result = lookup_reasoning_artifact(
            agent_profile_id=profile_id,
            since_ts=since,
            until_ts=until,
            limit=10,
        )
        assert len(result) == 3

        # Ordered by timestamp DESC
        timestamps = [r["timestamp"] for r in result]
        assert timestamps == sorted(timestamps, reverse=True), "Result not in DESC order"

        # limit=1 returns only 1 row
        limited = lookup_reasoning_artifact(
            agent_profile_id=profile_id,
            since_ts=since,
            until_ts=until,
            limit=1,
        )
        assert len(limited) == 1
    finally:
        cleanup_conn = get_analytics_conn()
        with cleanup_conn.cursor() as cur:
            cur.execute(CLEANUP_SQL, (profile_id,))
        cleanup_conn.commit()
        cleanup_conn.close()
