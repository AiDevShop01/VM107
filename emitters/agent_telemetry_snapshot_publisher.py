"""Agent Telemetry Snapshot Publisher — Phase 74 producer.

Long-running sibling service that maintains the
`vm107:agent_telemetry:snapshot` Redis key read by VM100's
`mission_control.telemetry.agent_activity_client.get_agent_activity_snapshot`,
which feeds the Mission Control telemetry strip Agents panel.

Wiring:
  - Subscribes to the `vm107.agent_telemetry` PubSub channel that the
    existing `AgentTelemetryEmitter` library publishes to whenever an
    agent does real work (REAL_ACTIVITY) or sends a HEARTBEAT_IDLE.
  - Keeps an in-memory per-agent state map keyed by agent_id (the 14
    locked IDs from REQ-66-4 / CONTEXT.md §5).
  - Every N seconds writes the snapshot to the Redis key as a JSON list.

The reason this is a separate process instead of a function call inside the
existing emitter library: the library is per-event (one Redis publish per
emit). VM100 wants a single key it can GET on every dashboard tick, so we
need a coalescing aggregator with a fixed cadence. This service IS that
aggregator.

Snapshot shape (one entry per locked agent):

    [{
        "agent_id":         str,
        "status":           "OK" | "IDLE" | "STALE" | "UNKNOWN",
        "current_activity": str | None,
        "event_type":       "REAL_ACTIVITY" | "HEARTBEAT_IDLE" | None,
        "last_emit_at":     ISO8601 str | None,
        "degraded":         bool,
    }]

Status thresholds:
    OK     — last emit < 60 s ago
    IDLE   — last emit < 5 min ago
    STALE  — last emit < 30 min ago
    UNKNOWN — no recent emit (>30 min) or never seen

Env vars (fail-fast):
    AGENT_TELEMETRY_REDIS_URL          — Redis URL (matches VM100's VM107_TELEMETRY_REDIS_URL)
    AGENT_TELEMETRY_PUBLISH_INTERVAL_SEC — Snapshot write cadence (default 5)
    AGENT_TELEMETRY_HEALTHZ_PORT       — HTTP port for /healthz (default 8091)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import redis as redis_lib

# Reuse the LOCKED 14 ids + the channel name from the emitter library so the
# contract stays single-sourced. Importing only constants — no heavy startup.
from emitters.agent_telemetry_emitter import CHANNEL_NAME, LOCKED_AGENT_IDS

log = logging.getLogger("agent_telemetry_snapshot_publisher")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_SNAPSHOT_KEY = "vm107:agent_telemetry:snapshot"
_HEALTHZ_SUCCESS_TTL_SEC = 30


def _required(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        log.error("missing env: %s", key)
        sys.exit(2)
    return v


def _classify_status(last_emit_at: datetime | None, now_utc: datetime) -> str:
    if last_emit_at is None:
        return "UNKNOWN"
    age = now_utc - last_emit_at
    if age < timedelta(seconds=60):
        return "OK"
    if age < timedelta(minutes=5):
        return "IDLE"
    if age < timedelta(minutes=30):
        return "STALE"
    return "UNKNOWN"


class _PerAgentState:
    """In-memory cache of the most recent event per agent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # agent_id → {last_emit_at: datetime, summary: str, event_type: str}
        self._state: dict[str, dict] = {}

    def record(self, payload: dict) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id or agent_id not in LOCKED_AGENT_IDS:
            return
        ts_raw = payload.get("generated_at")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)
        with self._lock:
            self._state[agent_id] = {
                "last_emit_at": ts,
                "summary": payload.get("summary"),
                "event_type": payload.get("event_type"),
            }

    def snapshot(self) -> list[dict]:
        now_utc = datetime.now(timezone.utc)
        with self._lock:
            state_copy = {k: dict(v) for k, v in self._state.items()}
        out: list[dict] = []
        for agent_id in sorted(LOCKED_AGENT_IDS):
            row = state_copy.get(agent_id)
            last_emit = row["last_emit_at"] if row else None
            status = _classify_status(last_emit, now_utc)
            out.append({
                "agent_id": agent_id,
                "status": status,
                "current_activity": (row["summary"] if row and status == "OK" else None),
                "event_type": row["event_type"] if row else None,
                "last_emit_at": last_emit.isoformat() if last_emit else None,
                "degraded": status in ("STALE", "UNKNOWN"),
            })
        return out


class _HealthHandler(BaseHTTPRequestHandler):
    state: dict[str, float] = {"last_publish_ts": 0.0}

    def do_GET(self):  # noqa: N802
        if self.path != "/healthz":
            self.send_response(404); self.end_headers(); return
        age = time.time() - _HealthHandler.state["last_publish_ts"]
        ok = age < _HEALTHZ_SUCCESS_TTL_SEC
        body = json.dumps({"ok": ok, "last_publish_age_sec": round(age, 1)}).encode()
        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 (silence stdlib chatter)
        return


def _start_healthz(port: int) -> None:
    srv = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("healthz listening on :%d", port)


def _start_pubsub_listener(
    redis_client: redis_lib.Redis,
    state: _PerAgentState,
    stop: threading.Event,
) -> None:
    """Subscribe to the telemetry PubSub channel and feed `state`."""
    def _loop():
        while not stop.is_set():
            try:
                pubsub = redis_client.pubsub()
                pubsub.subscribe(CHANNEL_NAME)
                log.info("subscribed channel=%s", CHANNEL_NAME)
                for message in pubsub.listen():
                    if stop.is_set():
                        break
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if not data:
                        continue
                    try:
                        payload = json.loads(data) if isinstance(data, str) else json.loads(data.decode("utf-8"))
                    except Exception as exc:
                        log.debug("pubsub.json_decode_failed: %s", exc)
                        continue
                    state.record(payload)
            except Exception as exc:
                log.warning("pubsub loop crashed, will reconnect: %s", exc)
                stop.wait(2)

    threading.Thread(target=_loop, daemon=True).start()


def main() -> int:
    redis_url = _required("AGENT_TELEMETRY_REDIS_URL")
    interval_sec = float(os.environ.get("AGENT_TELEMETRY_PUBLISH_INTERVAL_SEC", "5"))
    healthz_port = int(os.environ.get("AGENT_TELEMETRY_HEALTHZ_PORT", "8091"))

    r = redis_lib.from_url(redis_url, decode_responses=True)
    state = _PerAgentState()
    _start_healthz(healthz_port)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    _start_pubsub_listener(r, state, stop)

    log.info(
        "publish loop interval=%.1fs key=%s locked_agents=%d",
        interval_sec, _SNAPSHOT_KEY, len(LOCKED_AGENT_IDS),
    )
    while not stop.is_set():
        try:
            snap = state.snapshot()
            r.set(_SNAPSHOT_KEY, json.dumps(snap))
            _HealthHandler.state["last_publish_ts"] = time.time()
        except Exception as exc:
            log.exception("publish failed: %s", exc)
        stop.wait(interval_sec)

    log.info("shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
