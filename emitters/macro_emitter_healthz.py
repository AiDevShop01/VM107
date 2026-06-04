"""Phase 83 Plan 10 — /healthz HTTP endpoint for the vm107-macro-emitter sibling service.

Three dependency checks:
  1. calendar_ok   — GET MACRO_EMITTER_CALENDAR_URL/api/v1/health (HTTP 200)
  2. redis_ok      — redis.Redis.from_url(MACRO_EMITTER_REDIS_URL).ping()
  3. emission_ok   — _LAST_EMISSION_AT < MACRO_EMITTER_MAX_EMISSION_AGE_SEC seconds ago

Responds 200 {"ok": true, "deps": {...}} when all checks pass.
Responds 503 {"ok": false, "deps": {...}} when any check fails.

Env vars:
  MACRO_EMITTER_REDIS_URL         — required (read from emitter module env block)
  MACRO_EMITTER_CALENDAR_URL      — required
  MACRO_EMITTER_HEALTHZ_PORT      — optional (default 8090)
  MACRO_EMITTER_MAX_EMISSION_AGE_SEC — optional (default 1200 = 2 * max cadence 600s)

serve_healthz_background() starts an HTTP server on a daemon thread; called by main()
in intelligence_feed_macro_emitter before the loop starts.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

import httpx
import redis

log = logging.getLogger(__name__)

_HEALTHZ_PORT: int = int(os.environ.get("MACRO_EMITTER_HEALTHZ_PORT", "8090"))
_MAX_EMISSION_AGE_SEC: int = int(
    os.environ.get("MACRO_EMITTER_MAX_EMISSION_AGE_SEC", "1200")
)

# Module-level getter set by serve_healthz_background(). Captures the
# running emitter's _LAST_EMISSION_AT so the handler can read it without
# re-importing the emitter module.
#
# WHY: the emitter is started with `python -m emitters.intelligence_feed_macro_emitter`,
# which loads it as `__main__`. A subsequent `import emitters.intelligence_feed_macro_emitter`
# returns a SEPARATE module instance with its own _LAST_EMISSION_AT=None.
# Reading from that import never reflects the running loop's state.
# Passing a callable from main() closes the loop over the live global.
_GET_LAST_EMISSION_AT: Optional[Callable[[], Optional[datetime]]] = None


class HealthzHandler(BaseHTTPRequestHandler):
    """HTTP handler for /healthz.

    Reads last emission timestamp via the _GET_LAST_EMISSION_AT closure
    (set by serve_healthz_background) so the handler reflects the
    running emitter loop's state regardless of how the emitter was launched.
    """

    def do_GET(self) -> None:
        """Handle GET /healthz — always responds (never raises)."""
        if self.path != "/healthz":
            self._write(404, {"ok": False, "error": "not found"})
            return

        deps: dict[str, bool] = {}
        all_ok = True

        # ── Redis check ────────────────────────────────────────────────────
        redis_url = os.environ.get("MACRO_EMITTER_REDIS_URL", "")
        try:
            r = redis.Redis.from_url(redis_url)
            r.ping()
            deps["redis"] = True
        except Exception as exc:
            log.warning("healthz: Redis ping failed: %r", exc)
            deps["redis"] = False
            all_ok = False

        # ── Calendar check ─────────────────────────────────────────────────
        # VM100 exposes /api/health (not /api/v1/health) — the Plan 10
        # hardcoded path was wrong, causing healthz to always report
        # calendar:false even when VM100 was perfectly healthy.
        calendar_url = os.environ.get("MACRO_EMITTER_CALENDAR_URL", "")
        try:
            resp = httpx.get(
                f"{calendar_url.rstrip('/')}/api/health",
                timeout=3.0,
            )
            deps["calendar"] = resp.status_code == 200
            if not deps["calendar"]:
                all_ok = False
        except Exception as exc:
            log.warning("healthz: calendar ping failed: %r", exc)
            deps["calendar"] = False
            all_ok = False

        # ── Last emission freshness check ──────────────────────────────────
        # Read via the closure registered by serve_healthz_background.
        # Falling back to re-import would hit the __main__ vs imported-module
        # gotcha and always return None — see _GET_LAST_EMISSION_AT docstring.
        if _GET_LAST_EMISSION_AT is not None:
            try:
                last = _GET_LAST_EMISSION_AT()
            except Exception as exc:
                log.warning("healthz: getter raised: %r", exc)
                last = None
        else:
            last = None

        if last is None:
            # Service just started — treat as stale
            deps["emission_fresh"] = False
            all_ok = False
        else:
            now = datetime.now(timezone.utc)
            age_sec = (now - last).total_seconds()
            max_age = int(os.environ.get("MACRO_EMITTER_MAX_EMISSION_AGE_SEC", "1200"))
            deps["emission_fresh"] = age_sec <= max_age
            if not deps["emission_fresh"]:
                all_ok = False

        body = {"ok": all_ok, "deps": deps}
        status = 200 if all_ok else 503
        self._write(status, body)

    def _write(self, status: int, body: dict) -> None:
        """Write JSON response."""
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        """Suppress default access log spam — use structured logging only."""
        log.debug("healthz: " + fmt, *args)


def serve_healthz_background(
    port: int | None = None,
    get_last_emission_at: Optional[Callable[[], Optional[datetime]]] = None,
) -> None:
    """Start the /healthz HTTP server on a daemon thread.

    Called once from intelligence_feed_macro_emitter.main() before the loop.
    The daemon thread dies automatically when the main process exits.

    Args:
        port: HTTP port (default MACRO_EMITTER_HEALTHZ_PORT or 8090).
        get_last_emission_at: zero-arg callable returning the running
            emitter's _LAST_EMISSION_AT. Required for emission_fresh check
            to work — see _GET_LAST_EMISSION_AT module docstring.
    """
    global _GET_LAST_EMISSION_AT
    _GET_LAST_EMISSION_AT = get_last_emission_at

    effective_port = port or _HEALTHZ_PORT
    server = HTTPServer(("0.0.0.0", effective_port), HealthzHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="healthz-server",
        daemon=True,
    )
    thread.start()
    log.info("healthz server started on port %d", effective_port)
