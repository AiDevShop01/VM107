"""Phase 47 Wave 1: GET AI chat history for a journal entry.

GET /api/v1/trades/<journal_id>/ai/history
Registered via webapp.add_url_rule() in ui_server.py (parametric URL).

Reconstructs the rolling AI conversation from Mongo agent_envelopes,
ordered ascending by timestamp. Each envelope produces two message entries:
- user message (from input.message)
- agent message (from output.response, or failure placeholder)

X-API-KEY authentication required.
"""
from __future__ import annotations

import json
import logging

from flask import Response

from helpers.api import ApiHandler, Input, Output
from helpers.mongo import get_mongo_db

log = logging.getLogger(__name__)


class TradeAiHistory(ApiHandler):
    """GET /api/v1/trades/<journal_id>/ai/history — history reconstruction.

    Registered via webapp.add_url_rule() in helpers/ui_server.py.
    journal_id is read from request.view_args (Flask parametric URL).
    X-API-KEY authentication required.

    Response shape:
        {"messages": [...], "journal_id": str}

    Each envelope yields two message entries (user + agent) in ascending order.
    Failure envelopes yield an agent entry with:
        content="[Response failed — AI service error]", failed=True
    Degraded envelopes yield an agent entry with degraded=True.
    """

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: Input, request) -> Output:  # type: ignore[override]
        journal_id = (getattr(request, "view_args", None) or {}).get("journal_id", "").strip()
        if not journal_id:
            return Response(
                json.dumps({"error": "Missing journal_id"}),
                422,
                mimetype="application/json",
            )

        db = get_mongo_db()

        # Fetch all envelopes for this journal ordered ascending by timestamp.
        # The Mongo sparse index {journal_id: 1, timestamp: -1} (009 migration)
        # makes this efficient. We sort ascending here for chronological display.
        cursor = db["agent_envelopes"].find(
            {"journal_id": journal_id, "agent_id": "agent_zero"},
            sort=[("timestamp", 1)],
        )

        # Sort results client-side to guarantee ascending order even if cursor
        # returns out-of-order results in tests (mock iterators have no sort).
        envelope_docs = sorted(
            list(cursor),
            key=lambda d: (d.get("timestamp") or ""),
        )

        messages: list[dict] = []
        for env in envelope_docs:
            ts = env.get("timestamp")
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else ""
            env_id = env.get("envelope_id")
            status = env.get("status", "success")

            # User message (from input.message).
            user_msg = (env.get("input") or {}).get("message", "")
            messages.append({
                "role": "user",
                "content": user_msg,
                "timestamp": ts_str,
                "envelope_id": env_id,
            })

            # Agent message.
            if status == "failure":
                messages.append({
                    "role": "agent",
                    "content": "[Response failed — AI service error]",
                    "timestamp": ts_str,
                    "envelope_id": env_id,
                    "failed": True,
                })
            else:
                agent_content = (env.get("output") or {}).get("response", "")
                messages.append({
                    "role": "agent",
                    "content": agent_content,
                    "timestamp": ts_str,
                    "envelope_id": env_id,
                    "degraded": status == "degraded",
                })

        log.debug(
            "History for journal_id=%s: %d envelopes → %d messages",
            journal_id, len(envelope_docs), len(messages),
        )

        return Response(
            json.dumps({"messages": messages, "journal_id": journal_id}),
            200,
            mimetype="application/json",
        )
