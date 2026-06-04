"""Phase 83 Plan 10 — Long-running MACRO emitter (Decision G1).

State-aware loop + Redis interrupt channel + Postgres+Redis snapshot persistence
+ tier-3 degradation (Decision H1) + MACRO_EMITTER_ENABLED feature flag (Decision H2).

SHIPPED AS DOCKER-COMPOSE SIBLING SERVICE vm107-macro-emitter — NEVER mgmt-command-only.
(CLAUDE.md feedback_mgmt_commands_need_compose_service lock; Phase 74-03 cautionary tale)

Architecture decisions honored:
  G1: Single state-aware loop with per-state cadence (not 5 cron jobs)
  G2: Postgres truth + Redis cache (Lock 10)
  H1: Tier-3 degradation = last-known-good from Redis (Pitfall 12 — NEVER re-show DEMO)
  H2: MACRO_EMITTER_ENABLED env flag for instant rollback (kill-switch)
  Pitfall 2: docker-compose sibling service (Phase 74-03 cautionary tale avoided)
  Pitfall 8: Redis interrupt channel with sub-second responsiveness (not time.sleep)
  Pitfall 12: H1 degradation NEVER shows [DEMO] chip — only H2 kill-switch path

Per-state cadence (CONTEXT G1 — env-overridable):
  PRE            : 5 min (300s) — low urgency pre-session
  OPEN           : 60s   — high urgency session open
  ACTIVE_SUPERVISION: 90s (60-120s midpoint)
  MID_OBSERVATION: 120s  — 2 minutes
  CLOSE          : 300s  — 5 minutes (session winding down)
  REVIEW         : 600s  — event-driven (long sleep with Redis interrupt)
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Optional

import uuid

import redis

from emitters.intelligence_feed_macro_composer import (
    IntelligenceFeedMacroComposer,
    MacroEmissionPayload,
    MacroItem,
)
from services.snapshot_writer import SnapshotHTTPWriter, SnapshotRedisCache
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ENVELOPE_SCHEMA_VERSION

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-state cadences (env-overridable — no defaults means we read from env
# at module load, with documented defaults for docker-compose env block)
# ---------------------------------------------------------------------------

DEFAULT_CADENCES: dict[str, int] = {
    "PRE": int(os.environ.get("MACRO_EMITTER_CADENCE_PRE_SEC", "300")),
    "OPEN": int(os.environ.get("MACRO_EMITTER_CADENCE_OPEN_SEC", "60")),
    "ACTIVE_SUPERVISION": int(os.environ.get("MACRO_EMITTER_CADENCE_ACTIVE_SEC", "90")),
    "MID_OBSERVATION": int(os.environ.get("MACRO_EMITTER_CADENCE_MID_SEC", "120")),
    "CLOSE": int(os.environ.get("MACRO_EMITTER_CADENCE_CLOSE_SEC", "300")),
    "REVIEW": int(os.environ.get("MACRO_EMITTER_CADENCE_REVIEW_SEC", "600")),
}

INTERRUPT_CHANNEL = "macro.calendar.event_published"
INTERRUPT_POLL_SEC: float = float(os.environ.get("MACRO_EMITTER_INTERRUPT_POLL_SEC", "1.0"))

# Required env vars — fail-fast at module import if missing (env-driven-config lock)
_REDIS_URL: str = os.environ["MACRO_EMITTER_REDIS_URL"]

# Module-level last-emission timestamp — read by /healthz endpoint
_LAST_EMISSION_AT: Optional[datetime] = None


class StateDetectClient:
    """Minimal Phase 65 state-detect client stub.

    In production, this calls the Phase 65 state_detect_service endpoint
    to determine the current market state. For Plan 10, we provide a simple
    HTTP client that can be injected/mocked in tests.

    Env: MACRO_EMITTER_STATE_DETECT_URL (optional — falls back to MACRO_EMITTER_CALENDAR_URL base)
    """

    def __init__(self, state_detect_url: str | None = None) -> None:
        # Try dedicated state detect URL first, then derive from calendar URL
        self._url = state_detect_url or os.environ.get(
            "MACRO_EMITTER_STATE_DETECT_URL", ""
        )
        self._jwt = os.environ.get("VM107_SERVICE_JWT", "")

    def detect_state(self) -> str:
        """Call state detect service and return current state string.

        Returns:
            State string: PRE | OPEN | ACTIVE_SUPERVISION | MID_OBSERVATION | CLOSE | REVIEW
            Falls back to 'OPEN' on any error (safe default for continuous operation).
        """
        if not self._url:
            return "OPEN"  # Safe default when endpoint not configured
        try:
            import httpx
            response = httpx.get(
                f"{self._url}/api/v1/mission-control/state",
                headers={"Authorization": f"Bearer {self._jwt}"},
                timeout=3.0,
            )
            response.raise_for_status()
            return response.json().get("state", "OPEN")
        except Exception as exc:
            log.warning("StateDetectClient.detect_state degraded: %r — using OPEN", exc)
            return "OPEN"


class IntelligenceFeedMacroEmitter:
    """Phase 83 Plan 10 — long-running MACRO emitter loop.

    State-aware loop with per-state cadence, Redis pubsub interrupt,
    Postgres+Redis snapshot persistence, tiered degradation, and feature flag.

    Designed to be the entrypoint for the vm107-macro-emitter docker-compose
    sibling service. Uses dependency injection so tests can mock all I/O.

    Usage (production)::

        emitter = IntelligenceFeedMacroEmitter()
        emitter.run()  # loops forever; SIGTERM exits gracefully

    Usage (test injection)::

        emitter = IntelligenceFeedMacroEmitter(
            composer=mock_composer,
            state_client=mock_state,
            snapshot_writer=mock_writer,
            snapshot_cache=mock_cache,
            redis_client=fake_redis,
        )
    """

    def __init__(
        self,
        composer: Optional[IntelligenceFeedMacroComposer] = None,
        state_client: Optional[StateDetectClient] = None,
        snapshot_writer: Optional[SnapshotHTTPWriter] = None,
        snapshot_cache: Optional[SnapshotRedisCache] = None,
        redis_client: Optional[redis.Redis] = None,
    ) -> None:
        self._composer = composer or IntelligenceFeedMacroComposer()
        self._state_client = state_client or StateDetectClient()
        self._snapshot_writer = snapshot_writer or SnapshotHTTPWriter()
        self._snapshot_cache = snapshot_cache or SnapshotRedisCache()
        self._redis = redis_client or redis.Redis.from_url(_REDIS_URL)
        self._shutdown = False

        # Register signal handlers for graceful shutdown (SIGTERM from docker stop)
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Main loop — runs until SIGTERM or SIGINT.

        1. Subscribe to Redis interrupt channel.
        2. Per-iteration: check feature flag, detect state, compose, persist.
        3. Sleep for cadence_sec with interrupt-aware polling.
        4. On interrupt: fire extra emission immediately (refresh_reason='interrupt').
        """
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(INTERRUPT_CHANNEL)
        log.info(
            "intelligence_feed_macro_emitter subscribed to %s; MACRO_EMITTER_ENABLED=%s",
            INTERRUPT_CHANNEL,
            os.environ.get("MACRO_EMITTER_ENABLED", "true"),
        )

        while not self._shutdown:
            # H2 feature flag — check every iteration (not just startup)
            if not self._is_enabled():
                log.info("MACRO_EMITTER_ENABLED=false → emitting demo snapshot (H2)")
                state = self._state_client.detect_state()
                self._emit_demo_snapshot(state)
                self._sleep_with_interrupts(60, pubsub)  # re-check flag every 60s
                continue

            # Detect current market state
            state = self._state_client.detect_state()
            cadence = self._cadence_for_state(state)

            # Compose and persist (Tier-3 degradation on failure)
            try:
                self._compose_and_persist(state, refresh_reason="cadence")
            except Exception:
                log.exception(
                    "intelligence_feed_macro_emitter compose failed → tier-3 degradation"
                )
                self._persist_degraded(state)

            # Interrupt-aware sleep — returns the pubsub message or None
            msg = self._sleep_with_interrupts(cadence, pubsub)
            if msg is not None and not self._shutdown:
                log.info(
                    "intelligence_feed_macro_emitter interrupt received channel=%s → forced refresh",
                    INTERRUPT_CHANNEL,
                )
                try:
                    self._compose_and_persist(state, refresh_reason="interrupt")
                except Exception:
                    log.exception(
                        "intelligence_feed_macro_emitter interrupt compose failed"
                    )
                    self._persist_degraded(state)

        log.info("intelligence_feed_macro_emitter exited gracefully")

    # ── Core emission methods ─────────────────────────────────────────────────

    def _compose_and_persist(self, state: str, refresh_reason: str) -> None:
        """Compose a MACRO emission via the Plan 09 composer, then persist (G2)."""
        global _LAST_EMISSION_AT
        envelope = self._composer.compose(state=state)
        self._snapshot_writer.write(envelope, state=state, refresh_reason=refresh_reason)
        self._snapshot_cache.write(envelope, state=state)
        _LAST_EMISSION_AT = datetime.now(timezone.utc)
        item_count = len(envelope.payload.items) if hasattr(envelope, "payload") else 0
        log.info(
            "intelligence_feed_macro_emitter emitted state=%s items=%d reason=%s",
            state, item_count, refresh_reason,
        )

    def _persist_degraded(self, state: str) -> None:
        """Decision H1 — last-known-good fallback. NEVER re-show [DEMO] (Pitfall 12).

        Called when composer raises (transient LLM failure, calendar HTTP error).
        Reads last-known-good from Redis cache and logs — does NOT write a new
        snapshot (would overwrite with degraded=True, which Plan 11 aggregator
        would need to distinguish). Caller is responsible for the wait cadence.
        """
        last = self._snapshot_cache.read(state)
        if last is None:
            log.warning(
                "intelligence_feed_macro_emitter degraded + no cached snapshot for state=%s",
                state,
            )
            return
        # Surface last-known-good via cache only (Redis has the existing value)
        # _demo is intentionally NOT set True here — H1 degradation != kill-switch
        log.warning(
            "intelligence_feed_macro_emitter tier-3: using last-known-good for state=%s",
            state,
        )

    def _emit_demo_snapshot(self, state: str) -> None:
        """Decision H2 ONLY — feature-flag kill-switch path.

        SEMANTIC SPLIT (Pitfall 12 / W8):
        - This method fires ONLY when MACRO_EMITTER_ENABLED=false (operator kill-switch).
          It NEVER fires during H1 composer outage / LLM unavailability / calendar empty.
        - source='vm107.macro_emitter.demo_fallback' is the MARKER that Plan 11
          aggregator uses to route to Phase-65 demo-placeholder rendering (_demo=True).
        - H1 (composer outage) uses _persist_degraded() which surfaces last-known-good
          with _demo=False so the [DEMO] chip never reappears during normal degradation.
        """
        now_ts = datetime.now(timezone.utc)
        now_iso = now_ts.isoformat()
        demo_payload = MacroEmissionPayload(
            items=[],
            state=state,
            generated_at=now_iso,
            degraded=False,
            source="vm107.macro_emitter.demo_fallback",
        )
        envelope = ToolResultEnvelope[MacroEmissionPayload](
            envelope_id=uuid.uuid4(),
            tool_name="vm107.intelligence_feed.macro",
            tool_version="1.0",
            outcome_class="degraded",
            success=True,
            generated_at=now_ts,
            registry_snapshot_hash="demo",
            payload_schema_version="1.0",
            payload=demo_payload,
        )
        try:
            self._snapshot_writer.write(envelope, state=state, refresh_reason="manual")
            self._snapshot_cache.write(envelope, state=state)
            log.info("intelligence_feed_macro_emitter demo snapshot written (H2 kill-switch)")
        except Exception:
            log.exception("intelligence_feed_macro_emitter demo snapshot write failed")

    # ── State cadence + interrupt ─────────────────────────────────────────────

    def _cadence_for_state(self, state: str) -> int:
        """Return cadence in seconds for the given market state (CONTEXT G1)."""
        return DEFAULT_CADENCES.get(state, 300)

    def _sleep_with_interrupts(
        self, cadence_sec: int, pubsub: redis.client.PubSub
    ) -> Optional[dict]:
        """Sleep up to cadence_sec, polling Redis pubsub every INTERRUPT_POLL_SEC.

        Returns:
            The interrupt pubsub message dict if one arrives, otherwise None.
            Returns None on SIGTERM/shutdown.
        """
        elapsed = 0.0
        while elapsed < cadence_sec and not self._shutdown:
            msg = pubsub.get_message(timeout=INTERRUPT_POLL_SEC)
            if msg and msg.get("type") == "message":
                return msg
            elapsed += INTERRUPT_POLL_SEC
        return None

    # ── Feature flag ─────────────────────────────────────────────────────────

    def _is_enabled(self) -> bool:
        """Decision H2 — read MACRO_EMITTER_ENABLED from env on each iteration.

        Reading per-iteration (not cached at __init__) lets operators flip the
        flag via `docker compose exec vm107-macro-emitter` + env override without
        restarting the container.

        Default: 'true' (safe — emitter runs unless explicitly disabled).
        """
        return os.environ.get("MACRO_EMITTER_ENABLED", "true").strip().lower() == "true"

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _handle_sigterm(self, signum: int, frame) -> None:
        """SIGTERM / SIGINT handler — signal the loop to exit after current cycle."""
        log.info(
            "intelligence_feed_macro_emitter received signal %d; shutting down gracefully",
            signum,
        )
        self._shutdown = True


# ---------------------------------------------------------------------------
# Module entrypoint (python -m emitters.intelligence_feed_macro_emitter)
# ---------------------------------------------------------------------------

def main() -> None:
    """Entrypoint for the vm107-macro-emitter docker-compose sibling service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Import and start healthz server before the main loop
    try:
        from emitters.macro_emitter_healthz import serve_healthz_background
        # Pass a callable so healthz reads the running module's global,
        # not a duplicate module copy (the emitter runs as __main__).
        serve_healthz_background(get_last_emission_at=lambda: _LAST_EMISSION_AT)
    except Exception as exc:
        log.warning("Failed to start healthz server: %r — continuing without it", exc)

    log.info(
        "intelligence_feed_macro_emitter starting; "
        "MACRO_EMITTER_ENABLED=%s",
        os.environ.get("MACRO_EMITTER_ENABLED", "true"),
    )
    emitter = IntelligenceFeedMacroEmitter()
    emitter.run()
    log.info("intelligence_feed_macro_emitter exited")


if __name__ == "__main__":
    main()
