"""VM107 ApiHandler — GET /api/v1/telemetry/cost

Feeds the Mission Control telemetry strip Cost panel (Phase 74).

Aggregates `fingpt_agents.agent_runs` cost rows into:

    {
        session_usd          — last 1 hour of spend (approximates an active
                               work session; agents are mostly long-tailed)
        today_usd            — sum since UTC midnight
        mtd_usd              — sum since UTC first of month
        sparkline_24h        — 24-hour rolling hourly costs (oldest → newest)
        conv_type_stacked_bar — per-conv-type today-spend rows
    }

The VM100 client (`cost_client.py`) applies the budget-percent math itself
using `DAILY_AI_BUDGET_USD` — this endpoint returns raw USD only.

Auth: X-API-KEY required (same service-to-service contract as the AI
routing endpoint).

Failure mode: Mongo unavailable → demo snapshot with `_demo: True` flags.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from helpers.api import ApiHandler, Response

log = logging.getLogger(__name__)


_CONV_TYPES: tuple[str, ...] = (
    "pre-trade", "macro", "execution", "reflection", "research", "strategy",
)
_SESSION_WINDOW_HOURS = 1
_SPARKLINE_BUCKETS = 24


def _empty_snapshot() -> dict[str, Any]:
    return {
        "session_usd": 0.0,
        "today_usd": 0.0,
        "mtd_usd": 0.0,
        "sparkline_24h": [0.0] * _SPARKLINE_BUCKETS,
        "conv_type_stacked_bar": [
            {"conv_type": ct, "spend_usd": 0.0, "spend_pct": 0.0, "_demo": True}
            for ct in _CONV_TYPES
        ],
        "stale": True,
        "_demo": True,
    }


def _mongo_client():
    """Return a pymongo client or None when Mongo isn't reachable."""
    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        return None
    try:
        from pymongo import MongoClient
        return MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry.cost.mongo_client_failed: %s", exc)
        return None


def _build_snapshot(mongo) -> dict[str, Any]:
    """Aggregate cost rollups. Caller handles mongo=None."""
    coll = mongo.fingpt_agents.agent_runs
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    session_start = now_utc - timedelta(hours=_SESSION_WINDOW_HOURS)
    sparkline_start = now_utc - timedelta(hours=_SPARKLINE_BUCKETS)
    month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Pull MTD docs once — covers every other window via in-memory filters
    # (the volume is bounded by daily agent activity; MTD is a few thousand
    # rows at the most for a single user).
    docs = list(
        coll.find(
            {"created_at": {"$gte": month_start}},
            projection={
                "_id": 0,
                "cost_usd": 1, "created_at": 1, "conversation_type": 1,
            },
        )
    )

    if not docs:
        snap = _empty_snapshot()
        snap["stale"] = False
        snap["_demo"] = False
        for r in snap["conv_type_stacked_bar"]:
            r["_demo"] = False
        return snap

    def _cost(d):
        return float(d.get("cost_usd") or 0)

    session_usd = round(sum(_cost(d) for d in docs if d.get("created_at") and d["created_at"] >= session_start), 4)
    today_usd = round(sum(_cost(d) for d in docs if d.get("created_at") and d["created_at"] >= today_start), 4)
    mtd_usd = round(sum(_cost(d) for d in docs), 4)

    # 24-hour hourly sparkline — bucket index 0 is oldest hour, 23 is current.
    sparkline = [0.0] * _SPARKLINE_BUCKETS
    for d in docs:
        ts = d.get("created_at")
        if not ts or ts < sparkline_start:
            continue
        hours_old = int((now_utc - ts).total_seconds() // 3600)
        idx = _SPARKLINE_BUCKETS - 1 - hours_old
        if 0 <= idx < _SPARKLINE_BUCKETS:
            sparkline[idx] = round(sparkline[idx] + _cost(d), 4)

    # Per-conv-type today spend
    by_ct: dict[str, float] = defaultdict(float)
    for d in docs:
        if d.get("created_at") and d["created_at"] >= today_start:
            ct = d.get("conversation_type")
            if ct in _CONV_TYPES:
                by_ct[ct] += _cost(d)

    conv_type_stacked_bar = [
        {
            "conv_type": ct,
            "spend_usd": round(by_ct.get(ct, 0.0), 4),
            "spend_pct": round((by_ct.get(ct, 0.0) / today_usd * 100), 2) if today_usd > 0 else 0.0,
        }
        for ct in _CONV_TYPES
    ]

    return {
        "session_usd": session_usd,
        "today_usd": today_usd,
        "mtd_usd": mtd_usd,
        "sparkline_24h": sparkline,
        "conv_type_stacked_bar": conv_type_stacked_bar,
        "stale": False,
        "_demo": False,
    }


class TelemetryCostHandler(ApiHandler):
    """GET /api/v1/telemetry/cost — fleet cost rollup."""

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: dict, request) -> dict | Response:
        mongo = _mongo_client()
        if mongo is None:
            return _empty_snapshot()
        try:
            return _build_snapshot(mongo)
        except Exception as exc:  # noqa: BLE001
            log.exception("telemetry.cost.build_failed: %s", exc)
            return _empty_snapshot()
