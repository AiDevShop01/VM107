"""Phase 85 Plan 02 — B1 Persistent Reasoning Artifact persister extension.

Extension slot 20 in reasoning_stream_end (fires AFTER _10_mask_end.py).

Fires only for agent profiles with agent_profile_id starting with "vm107.macro_".
For any other profile, returns early with no side effects.

On macro_* profile invocation:
- Reads reasoning/response fields from agent.get_data()
- INSERTs one row into agent_reasoning_artifact in tradetracker_analytics
- Uses get_analytics_conn() from Plan 85-01 (psycopg2, direct write)

WORM semantics:
- No UPDATE/DELETE path exists in this extension
- DB-level REVOKE enforced by phase85_create_b1_table management command
- Contract-level frozen=True enforced by ReasoningArtifactContract

Error handling:
- B1 is observability — it MUST NOT crash the agent loop
- Any exception is caught, logged at ERROR level (visible in Wave 6 stability watch)
- Agent loop continues unaffected

See Plan 85-02 ARCHITECTURE for the full B1 design rationale.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from helpers.extension import Extension
from services.postgres_analytics_client import get_analytics_conn

logger = logging.getLogger(__name__)

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


class PersistReasoningArtifact(Extension):
    """Persist one B1 row per macro-agent invocation iteration at reasoning_stream_end."""

    async def execute(self, **kwargs):
        agent = kwargs.get("agent")
        if not agent:
            return

        profile_id = agent.get_data("profile_id") or ""
        if not profile_id.startswith("vm107.macro_"):
            # Not a macro agent — skip silently (no overhead, no log noise)
            return

        reasoning_text = agent.get_data("_reasoning_stream_text") or ""
        response_text = agent.get_data("_response_text") or ""

        tool_args_raw = agent.get_data("tool_args")
        tool_args_json = json.dumps(tool_args_raw) if tool_args_raw is not None else None

        citations_raw = agent.get_data("citations") or []
        citations_json = json.dumps(citations_raw)

        parent_env_id = agent.get_data("parent_envelope_id")

        params = {
            "artifact_id": str(uuid4()),
            "agent_profile_id": profile_id,
            "sub_profile_id": agent.get_data("sub_profile_id"),
            "iteration": agent.get_data("iteration") or 0,
            "parent_envelope_id": str(parent_env_id) if parent_env_id else None,
            "reasoning_text": reasoning_text,
            "reasoning_tokens": agent.get_data("reasoning_tokens") or 0,
            "response_text": response_text,
            "response_tokens": agent.get_data("response_tokens") or 0,
            "tool_called": agent.get_data("tool_called"),
            "tool_args": tool_args_json,
            "timestamp": datetime.now(timezone.utc),
            "model_version": agent.get_data("model_version") or "unknown",
            "prompt_version": agent.get_data("prompt_version") or "unknown",
            "confidence_self_report": None,  # Filled by future B5; null in Phase 85
            "citations": citations_json,
        }

        try:
            conn = get_analytics_conn()
            with conn, conn.cursor() as cur:
                cur.execute(INSERT_SQL, params)
            conn.close()
        except Exception as exc:
            # B1 is observability — must NOT crash the agent loop.
            # Log loudly (ERROR) so Wave 6 stability watch detects B1 outages.
            logger.error(
                "b1_persist_failed — agent_reasoning_artifact INSERT failed",
                extra={
                    "event": "b1_persist_failed",
                    "profile_id": profile_id,
                    "error": str(exc),
                },
            )
