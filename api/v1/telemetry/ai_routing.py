"""VM107 ApiHandler — GET /api/v1/telemetry/ai_routing

Feeds the Mission Control telemetry strip AI Routing panel (Phase 74).

Aggregates `fingpt_agents.agent_runs` documents written by the
`chat_model_call_after/_router_log_cost.py` and
`util_model_call_after/_20_router_log_cost.py` extension hooks and rolls
them up into:

    fleet_summary: {
        primary_model:      str   — most-used model in the window
        fleet_health:       str   — OK | WARNING | UNHEALTHY
        fallback_rate:      float — fraction of calls that fell back (0..1)
        avg_latency_ms:     int
        cost_today_usd:     float — sum of today's costs (UTC)
        fallback_trend:     str   — "improving" | "stable" | "worsening"
    }
    conv_type_rows: [               — one per locked CONV_TYPES below
        {conv_type, current_model, req_per_min, p50_ms, p95_ms,
         fallback_pct, spend_today_usd, fallback_chain,
         last_fallback_reason, last_fallback_time}
    ]

Auth:
    X-API-KEY required (service-to-service token, matches Phase 73-followup
    VM100↔VM107 service auth pattern used by the intelligence_feed handlers).

Failure mode:
    Mongo unavailable → return demo shape with `_demo: True` flags so the
    VM100 client + frontend keep their stale-graceful contract.
"""
from __future__ import annotations

import logging
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from helpers.api import ApiHandler, Response

log = logging.getLogger(__name__)


# Locked Phase 74 conversation_types — must match the frontend's
# CONV_TYPE_ORDER. Adding a 7th here requires a coordinated FE migration.
_CONV_TYPES: tuple[str, ...] = (
    "pre-trade", "macro", "execution", "reflection", "research", "strategy",
)

# Rolling window for fleet summary + conv-type stats. 24h gives the panel
# enough sample size on a quiet user without smearing today's behaviour into
# yesterday's noise. The cost_today_usd field uses a separate UTC-midnight
# bucket so the displayed dollars match the user's "today" intuition.
_WINDOW_HOURS = 24
_FALLBACK_HEALTH_WARN_PCT = 0.10   # 10% fallback → WARNING
_FALLBACK_HEALTH_BAD_PCT = 0.25    # 25% fallback → UNHEALTHY


def _empty_fleet_summary() -> dict[str, Any]:
    return {
        "primary_model": "unknown",
        "fleet_health": "UNKNOWN",
        "fallback_rate": 0.0,
        "avg_latency_ms": 0,
        "cost_today_usd": 0.0,
        "fallback_trend": "stable",
        "_demo": True,
    }


def _empty_conv_row(ct: str) -> dict[str, Any]:
    return {
        "conv_type": ct,
        "current_model": "unknown",
        "req_per_min": 0,
        "p50_ms": 0,
        "p95_ms": 0,
        "fallback_pct": 0.0,
        "spend_today_usd": 0.0,
        "fallback_chain": [],
        "last_fallback_reason": None,
        "last_fallback_time": None,
        "_demo": True,
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "fleet_summary": _empty_fleet_summary(),
        "conv_type_rows": [_empty_conv_row(ct) for ct in _CONV_TYPES],
        "stale": True,
    }


def _mongo_client():
    """Return a pymongo client or None when Mongo isn't reachable.

    Reads MONGODB_URI directly — the per-request Mongo client is fine
    because the panel polls infrequently and pymongo internally pools
    connections.
    """
    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        return None
    try:
        from pymongo import MongoClient
        return MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetry.ai_routing.mongo_client_failed: %s", exc)
        return None


def _percentile(values: list[int | float], pct: float) -> int:
    """Nearest-rank percentile of `values` (0..100). 0 when empty."""
    if not values:
        return 0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return int(s[k])


def _classify_fleet_health(fallback_rate: float) -> str:
    if fallback_rate >= _FALLBACK_HEALTH_BAD_PCT:
        return "UNHEALTHY"
    if fallback_rate >= _FALLBACK_HEALTH_WARN_PCT:
        return "WARNING"
    return "OK"


def _compute_fallback_trend(now_rate: float, recent_rate: float) -> str:
    """Compare the older half of the window vs the newer half."""
    # Treat 0.5 percentage point as the noise floor.
    delta = recent_rate - now_rate
    if abs(delta) < 0.005:
        return "stable"
    return "worsening" if delta > 0 else "improving"


def _build_snapshot(mongo) -> dict[str, Any]:
    """Aggregate the rolling-window stats. Caller handles mongo=None."""
    coll = mongo.fingpt_agents.agent_runs
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=_WINDOW_HOURS)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    # The window splits in two equal halves for the trend calc.
    half_split = window_start + timedelta(hours=_WINDOW_HOURS / 2)

    docs = list(
        coll.find(
            {"created_at": {"$gte": window_start}},
            projection={
                "_id": 0,
                "model": 1, "latency_ms": 1, "cost_usd": 1,
                "fallback_used": 1, "created_at": 1,
                "conversation_type": 1, "path": 1,
            },
        )
    )

    if not docs:
        # Mongo reachable but no recent calls → return zeroed but not _demo.
        snapshot = _empty_snapshot()
        snapshot["stale"] = False
        snapshot["fleet_summary"]["_demo"] = False
        snapshot["fleet_summary"]["fleet_health"] = "OK"
        for r in snapshot["conv_type_rows"]:
            r["_demo"] = False
        return snapshot

    # ── Fleet summary ────────────────────────────────────────────────────
    total = len(docs)
    fallbacks = sum(1 for d in docs if d.get("fallback_used"))
    fallback_rate = fallbacks / total if total else 0.0
    latencies = [int(d.get("latency_ms") or 0) for d in docs]
    avg_latency_ms = int(statistics.mean(latencies)) if latencies else 0
    model_counts = Counter(d.get("model") or "unknown" for d in docs)
    primary_model = model_counts.most_common(1)[0][0] if model_counts else "unknown"
    cost_today_usd = float(sum(
        float(d.get("cost_usd") or 0)
        for d in docs
        if d.get("created_at") and d["created_at"] >= today_start
    ))

    # Trend: split into older half (pre-half_split) vs newer half (post).
    older = [d for d in docs if d.get("created_at") and d["created_at"] < half_split]
    newer = [d for d in docs if d.get("created_at") and d["created_at"] >= half_split]
    older_rate = (sum(1 for d in older if d.get("fallback_used")) / len(older)) if older else fallback_rate
    newer_rate = (sum(1 for d in newer if d.get("fallback_used")) / len(newer)) if newer else fallback_rate
    fallback_trend = _compute_fallback_trend(older_rate, newer_rate)

    fleet_summary = {
        "primary_model": primary_model,
        "fleet_health": _classify_fleet_health(fallback_rate),
        "fallback_rate": round(fallback_rate, 4),
        "avg_latency_ms": avg_latency_ms,
        "cost_today_usd": round(cost_today_usd, 4),
        "fallback_trend": fallback_trend,
        "_demo": False,
    }

    # ── Per-conv-type rows ───────────────────────────────────────────────
    by_ct: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        ct = d.get("conversation_type")
        if ct in _CONV_TYPES:
            by_ct[ct].append(d)

    minutes_in_window = _WINDOW_HOURS * 60
    conv_rows: list[dict[str, Any]] = []
    for ct in _CONV_TYPES:
        rows = by_ct.get(ct, [])
        if not rows:
            r = _empty_conv_row(ct)
            r["_demo"] = False
            conv_rows.append(r)
            continue
        row_latencies = [int(d.get("latency_ms") or 0) for d in rows]
        row_fallbacks = sum(1 for d in rows if d.get("fallback_used"))
        row_models = Counter(d.get("model") or "unknown" for d in rows)
        spend_today = float(sum(
            float(d.get("cost_usd") or 0)
            for d in rows
            if d.get("created_at") and d["created_at"] >= today_start
        ))
        # Last fallback for the inline expansion section.
        last_fb = next(
            (d for d in sorted(
                rows, key=lambda x: x.get("created_at") or datetime.min,
                reverse=True,
            ) if d.get("fallback_used")),
            None,
        )
        conv_rows.append({
            "conv_type": ct,
            "current_model": row_models.most_common(1)[0][0],
            "req_per_min": round(len(rows) / minutes_in_window, 3),
            "p50_ms": _percentile(row_latencies, 50),
            "p95_ms": _percentile(row_latencies, 95),
            "fallback_pct": round(row_fallbacks / len(rows), 4) if rows else 0.0,
            "spend_today_usd": round(spend_today, 4),
            # The fallback CHAIN is a property of the router config, not the
            # observed history. Surfacing it here would require a separate
            # pull from `model_routing.yaml` keyed by ct — deferred.
            "fallback_chain": [],
            "last_fallback_reason": None,
            "last_fallback_time": (
                last_fb["created_at"].isoformat()
                if last_fb and last_fb.get("created_at") else None
            ),
            "_demo": False,
        })

    return {
        "fleet_summary": fleet_summary,
        "conv_type_rows": conv_rows,
        "stale": False,
    }


class TelemetryAIRoutingHandler(ApiHandler):
    """GET /api/v1/telemetry/ai_routing — fleet + per-conv-type rollup."""

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # service-to-service token via requires_api_key

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
            log.exception("telemetry.ai_routing.build_failed: %s", exc)
            return _empty_snapshot()
