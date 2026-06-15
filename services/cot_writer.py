"""Phase 86 Plan 07 — Chain-of-Thought (CoT) trail writer for standalone agents.

Writes one row per agent invocation to the `agent_cot_trail` table in
tradetracker_analytics (Phase 70.5 WORM provenance store).

Table contract (agent_cot_trail):
    agent_id        TEXT NOT NULL       — e.g. "macro_historical_analyst"
    invocation_id   TEXT NOT NULL       — UUID string, unique per invocation
    prompt          TEXT                — the initial prompt sent to LLM
    tools_called    JSONB               — list of tool call events (may be empty)
    emit_text       TEXT                — the final narrative text emitted
    terminated_at   TIMESTAMPTZ         — when the agent terminated
    created_at      TIMESTAMPTZ DEFAULT now()

WORM semantics (Phase 70.5):
- INSERT only — no UPDATE or DELETE paths in this module
- DB-level REVOKE enforced separately (same pattern as agent_reasoning_artifact)

Error handling:
- CoT trail is observability — writes MUST NOT crash the agent
- Any exception is caught and logged at ERROR level

Env vars required (via postgres_analytics_client):
- POSTGRES_HOST, POSTGRES_ANALYTICS_DB, POSTGRES_USER, POSTGRES_PASSWORD
- POSTGRES_PORT (optional, default 5432)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_INSERT_SQL = """
INSERT INTO agent_cot_trail (
    agent_id,
    invocation_id,
    prompt,
    tools_called,
    emit_text,
    terminated_at
) VALUES (
    %(agent_id)s,
    %(invocation_id)s,
    %(prompt)s,
    %(tools_called)s,
    %(emit_text)s,
    %(terminated_at)s
)
"""


def write_cot_trail(
    agent_id: str,
    invocation_id: str,
    cot_events: list[dict[str, Any]],
    *,
    terminated_at: float,
) -> None:
    """Insert one agent_cot_trail row.

    Args:
        agent_id:       Agent identifier string, e.g. "macro_historical_analyst".
        invocation_id:  UUID string uniquely identifying this invocation.
        cot_events:     List of CoT event dicts (role + text entries).
        terminated_at:  Unix timestamp (float) when the agent terminated.

    Does not raise on DB errors — logs at ERROR level and returns gracefully
    (CoT trail is observability, must not crash the agent path).
    """
    from services.postgres_analytics_client import get_analytics_conn

    # Extract prompt and final emit text from the event log
    prompt_text = ""
    emit_text = ""
    tools_called: list[str] = []

    for event in cot_events:
        role = event.get("role", "")
        text = event.get("text", "")
        if role == "prompt":
            prompt_text = text
        elif role in ("emit", "emit_2"):
            emit_text = text  # last emit wins
        elif role == "tool_call":
            tools_called.append(text)

    terminated_at_dt = datetime.fromtimestamp(terminated_at, tz=timezone.utc)

    params = {
        "agent_id": agent_id,
        "invocation_id": invocation_id,
        "prompt": prompt_text,
        "tools_called": json.dumps(tools_called),
        "emit_text": emit_text,
        "terminated_at": terminated_at_dt,
    }

    try:
        conn = get_analytics_conn()
        with conn, conn.cursor() as cur:
            cur.execute(_INSERT_SQL, params)
        conn.close()
    except Exception as exc:
        # CoT trail is observability — must NOT crash the agent loop.
        log.error(
            "cot_trail_write_failed — agent_cot_trail INSERT failed: %s(%s)",
            type(exc).__name__,
            exc,
            extra={
                "event": "cot_trail_write_failed",
                "agent_id": agent_id,
                "invocation_id": invocation_id,
                "error": str(exc),
            },
        )
