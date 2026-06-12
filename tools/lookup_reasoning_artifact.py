"""Phase 85 Plan 02 — B1 lookup tool: query reasoning artifacts by id or profile+time.

Callable: lookup_reasoning_artifact(
    artifact_id=None,           # UUID str — fetch exactly one row
    agent_profile_id=None,      # str — fetch all rows for this profile (with time bounds)
    since_ts=None,              # datetime — inclusive lower bound (requires agent_profile_id)
    until_ts=None,              # datetime — exclusive upper bound (requires agent_profile_id)
    limit=100,                  # int — max rows returned (default 100)
)

Returns:
    list[dict] — rows as dicts with column names matching ReasoningArtifactContract fields.
    Empty list when no rows match.

Raises:
    RuntimeError — when neither artifact_id nor agent_profile_id is provided.

Notes:
- Queries tradetracker_analytics via get_analytics_conn() (Plan 85-01).
- Tool registration in agent profiles happens in Plan 85-13 (registry wiring).
  Do NOT add to allowed_tools in any profile in this plan.
- Connection is always closed in the finally block — caller does not need to manage it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.postgres_analytics_client import get_analytics_conn

SELECT_BY_ID = """
SELECT * FROM agent_reasoning_artifact
WHERE artifact_id = %s
LIMIT 1;
"""

SELECT_BY_PROFILE = """
SELECT * FROM agent_reasoning_artifact
WHERE agent_profile_id = %s
  AND timestamp >= %s
  AND timestamp < %s
ORDER BY timestamp DESC
LIMIT %s;
"""

# Sentinel timestamps used when caller passes None for since_ts / until_ts
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def lookup_reasoning_artifact(
    artifact_id: str | None = None,
    agent_profile_id: str | None = None,
    since_ts: datetime | None = None,
    until_ts: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return reasoning artifact rows matching the given filter.

    Exactly one of artifact_id or agent_profile_id must be provided.
    When querying by profile, since_ts defaults to epoch and until_ts to far future.

    Args:
        artifact_id:       UUID string — return exactly the matching row (or []).
        agent_profile_id:  Profile ID string — return up to `limit` rows.
        since_ts:          Inclusive lower bound for timestamp (default: epoch).
        until_ts:          Exclusive upper bound for timestamp (default: year 9999).
        limit:             Maximum number of rows returned (default: 100).

    Returns:
        List of row dicts with keys matching agent_reasoning_artifact column names.

    Raises:
        RuntimeError: Neither artifact_id nor agent_profile_id was provided.
    """
    if not artifact_id and not agent_profile_id:
        raise RuntimeError(
            "lookup_reasoning_artifact: must supply artifact_id or agent_profile_id"
        )

    conn = get_analytics_conn()
    try:
        with conn.cursor() as cur:
            if artifact_id:
                cur.execute(SELECT_BY_ID, (str(artifact_id),))
            else:
                effective_since = since_ts if since_ts is not None else _EPOCH
                effective_until = until_ts if until_ts is not None else _FAR_FUTURE
                cur.execute(
                    SELECT_BY_PROFILE,
                    (agent_profile_id, effective_since, effective_until, int(limit)),
                )
            col_names = [desc.name for desc in cur.description]
            return [dict(zip(col_names, row)) for row in cur.fetchall()]
    finally:
        conn.close()
