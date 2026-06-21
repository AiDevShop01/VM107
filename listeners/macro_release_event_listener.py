"""Phase 83 release-event subscriber → Brain goal fan-out (Phase 85 Plan 10).

Extended in Phase 89 Plan 03 (Wave 3) with reaction_settled_at handling per
Decision 3 and Pitfall 6 (backward-compat LISTENER-SIDE fill).

Subscribes to the ``macro.release_events`` Redis Pub/Sub channel.
On each well-formed message, calls ``create_macro_release_goal`` which creates a
``macro_release_analysis`` Brain goal and fans out 3 child tasks:

  1. vm107.macro_release_analyst         (no deps — fires immediately)
  2. vm107.macro_asset_exposure_analyst  (no deps — fires in parallel)
  3. vm107.macro_executive_summary_writer (depends on 1 + 2 — fires after both)

After reaction_settled_at elapses (Decision 3 — default T+30min for intraday,
per-indicator overrides in macro_contradiction_detector agent profile YAML),
the listener also dispatches ``vm107.macro_contradiction_detector``.

Phase 89 extension — reaction_settled_at contract:
  Events from the upstream Phase 83 publisher NOW INCLUDE ``reaction_settled_at``
  (a pre-deploy gate enforced by Plan 09 — D3 hard lock; no escape hatch here).
  For backward-compat with older events lacking the field, the LISTENER computes:
    reaction_settled_at = release_timestamp + per_indicator_reaction_window (default 30min)
  This is a defensive fill only — Plan 09 gate is the authoritative fix.

Ships as docker-compose sibling service ``vm107-macro-release-event-listener``.
See docker-compose.yml for the service definition.

CLAUDE.md locks honoured:
  - env-driven-no-fallbacks: REDIS_URL is _required() (no default).
  - mgmt-cmd-needs-compose-service: listener runs as a sibling service, never
    as a mgmt command or manual ``docker exec``.

Phase 83 payload contract (``macro.release_events`` channel):
  {
    "event_type": "macro_release",
    "indicator_id": "CPIAUCSL",
    "release_timestamp": "2026-06-12T12:30:00Z",
    "actual_value": 3.4,
    "consensus_value": 3.3,
    "prior_value": 3.2,
    "revision_flag": false,
    "source": "vm101.macro_calendar",
    "reaction_settled_at": "2026-06-12T13:00:00Z"  # Phase 89 extension (Plan 09 gate)
  }

event_id is NOT a standalone field in the Phase 83 contract; it is DERIVED as:
  f"{indicator_id}:{release_timestamp}"

The listener also accepts payloads with an explicit ``event_id`` field (forward-
compatible for future producers that may include it directly).

Runbook:
  To restart the listener after env changes (never use `docker restart`):
    docker compose up -d --force-recreate --no-deps vm107-macro-release-event-listener
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timedelta, timezone

from core.scheduling.macro_release_goal import (
    configure_default_orchestrator,
    create_macro_release_goal,
)
from core.scheduling.orchestrator_factory import build_default_orchestrator

# Phase 85.1 Plan 02 — PRIMARY WS publish path.
# _ws_publish_once routes through the shared dedup guard so both the listener-
# registered on_complete hook AND the dispatcher's defence-in-depth call site
# share the same _published_goal_ids set (W5 dedup contract).
try:
    from workers.task_dispatcher import _publish_once as _ws_publish_once  # type: ignore[import]
except ImportError:
    # Fallback: task_dispatcher not yet deployed (e.g. early boot or test-only env).
    # In this case, use the direct publisher without dedup guard.
    from publishers.macro_ws_invalidation import publish_indicator_updated  # type: ignore[import]
    def _ws_publish_once(goal_id: "str | None", indicator_id: str) -> None:
        publish_indicator_updated(indicator_id)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fail-fast env var resolution
# ---------------------------------------------------------------------------

def _required(key: str) -> str:
    """Return env var value or raise RuntimeError. No fallback defaults."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast "
            f"(env-driven-no-fallbacks lock, Phase 85 Plan 10)"
        )
    return v


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def _validate_payload(data: dict) -> None:
    """Raise ValueError if required fields are missing.

    Required: ``indicator_id`` (always needed to derive event_id and route the goal).
    Either ``event_id`` OR ``release_timestamp`` must be present so an event_id
    can be constructed.

    Args:
        data: Decoded JSON dict from the Redis message.

    Raises:
        ValueError: If a required field is absent.
    """
    if "indicator_id" not in data:
        raise ValueError("Missing required field: 'indicator_id'")
    if "event_id" not in data and "release_timestamp" not in data:
        raise ValueError(
            "Missing required field: must have 'event_id' or 'release_timestamp' "
            "to derive a unique event identifier"
        )


def _extract_event_id(data: dict) -> str:
    """Extract or derive the event_id from the payload.

    Prefers an explicit ``event_id`` field (forward-compat); falls back to
    deriving from ``indicator_id:release_timestamp`` (Phase 83 contract).
    """
    if "event_id" in data:
        return data["event_id"]
    return f"{data['indicator_id']}:{data['release_timestamp']}"


# ---------------------------------------------------------------------------
# Phase 89 — reaction_settled_at helpers (Decision 3 + Pitfall 6)
# ---------------------------------------------------------------------------

# Per-indicator reaction window (minutes) — mirrors macro_contradiction_detector profile YAML.
# This default table is the LISTENER-SIDE defensive fill for backward-compat events.
# The canonical source of truth is the agent profile YAML loaded via lookup_capability.
_DEFAULT_REACTION_WINDOW_MINUTES = 30

_PER_INDICATOR_REACTION_WINDOW: dict[str, int] = {
    "GDP": 1440,      # T+1d (slow-burn)
    "GDPC1": 1440,
    "CPIAUCSL": 30,
    "PAYEMS": 30,
    "UNRATE": 30,
    "FEDFUNDS": 30,
}


def compute_reaction_settled_at(
    event: dict,
    per_indicator_windows: dict[str, int] | None = None,
) -> datetime:
    """Compute or extract reaction_settled_at from a release event.

    Backward-compat LISTENER-SIDE fill for events lacking the field.
    Decision 3: default T+30min for intraday; per-indicator overrides.

    NOTE: This fill does NOT replace the upstream publisher fix. Plan 09
    enforces a pre-deploy gate (D3 hard lock) requiring publishers to
    populate reaction_settled_at going forward. This is defensive only.

    Args:
        event: Decoded event dict from the Redis channel.
        per_indicator_windows: Override map {indicator_id: minutes}.
                               If None, uses _PER_INDICATOR_REACTION_WINDOW.

    Returns:
        datetime (UTC) when reaction is considered settled.
    """
    # Prefer explicit field from publisher (Plan 09 canonical path)
    if "reaction_settled_at" in event and event["reaction_settled_at"]:
        ts = event["reaction_settled_at"]
        if isinstance(ts, str):
            # ISO 8601 → datetime (handle Z suffix and +00:00)
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts).astimezone(timezone.utc)
        return ts

    # Backward-compat: compute from release_timestamp + window
    release_ts_str = event.get("release_timestamp", "")
    if release_ts_str:
        release_ts = datetime.fromisoformat(
            release_ts_str.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    else:
        # Fallback: treat "now" as release time (edge case — log warning)
        logger.warning({
            "event": "phase89_reaction_settled_at_fallback",
            "reason": "event missing both reaction_settled_at and release_timestamp",
        })
        release_ts = datetime.now(tz=timezone.utc)

    windows = per_indicator_windows if per_indicator_windows is not None else _PER_INDICATOR_REACTION_WINDOW
    indicator_id: str = event.get("indicator_id", "")
    window_minutes = windows.get(indicator_id, _DEFAULT_REACTION_WINDOW_MINUTES)

    return release_ts + timedelta(minutes=window_minutes)


def should_dispatch_now(
    event: dict,
    reference_time: datetime | None = None,
    per_indicator_windows: dict[str, int] | None = None,
) -> bool:
    """Return True if reaction_settled_at has elapsed and detector should fire.

    Args:
        event: Decoded event dict from the Redis channel.
        reference_time: The "now" for comparison. Defaults to datetime.now(UTC).
        per_indicator_windows: Per-indicator window overrides (minutes).

    Returns:
        True if reaction_settled_at <= now; False to defer.
    """
    now = reference_time if reference_time is not None else datetime.now(tz=timezone.utc)
    settled_at = compute_reaction_settled_at(event, per_indicator_windows=per_indicator_windows)
    return settled_at <= now


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the macro release event listener loop.

    Subscribes to ``macro.release_events`` (or PHASE85_RELEASE_TOPIC if set),
    decodes each message, and calls ``create_macro_release_goal``.
    Exits cleanly on SIGTERM / SIGINT.
    """
    redis_url = _required("REDIS_URL")

    # PHASE85_RELEASE_TOPIC is the topic NAME (not a credential/URL), so a
    # canonical default is acceptable per CLAUDE.md. The no-fallback lock
    # targets credentials and service URLs — not topic routing constants.
    topic = os.environ.get("PHASE85_RELEASE_TOPIC", "macro.release_events")

    # Phase 85 Plan 10/11 — wire the production BrainOrchestrator before the
    # first message arrives. Plan 85-10's handoff note required this; we land
    # it here so the module-level default is set before pubsub.listen() fires.
    configure_default_orchestrator(build_default_orchestrator())

    import redis as redis_lib

    # socket_keepalive keeps the long-lived pubsub connection alive across
    # NAT/firewall idle drops in Docker bridge networks. Explicit timeout=None
    # ensures listen() blocks indefinitely instead of raising TimeoutError.
    r = redis_lib.from_url(
        redis_url,
        socket_keepalive=True,
        socket_timeout=None,
    )
    pubsub = r.pubsub()
    pubsub.subscribe(topic)
    logger.info({"event": "phase85_listener_started", "topic": topic})

    shutting_down: dict[str, bool] = {"flag": False}

    def _handle_signal(sig: int, _frame: object) -> None:
        logger.info({"event": "phase85_listener_shutdown", "signal": sig})
        shutting_down["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Outer reconnect loop: a socket-level failure inside pubsub.listen() must
    # not kill the worker. Recreate the connection and resume listening.
    while not shutting_down["flag"]:
        try:
            for msg in pubsub.listen():
                if shutting_down["flag"]:
                    break

                # Ignore Redis control messages (subscribe/psubscribe/unsubscribe)
                if msg.get("type") != "message":
                    continue

                try:
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    data = json.loads(raw)
                    _validate_payload(data)
                    event_id = _extract_event_id(data)
                    indicator_id: str = data["indicator_id"]

                    # Phase 85.1 Plan 02 — PRIMARY publish path via on_complete hook.
                    # The lambda captures indicator_id by value (default-arg pattern
                    # prevents late-binding closure bug when multiple events are queued).
                    # goal_id is None in the zero-arg call; the dedup guard uses it as
                    # a fallback key so the dispatch defence-in-depth path can suppress
                    # double-publish for this goal when it fires.
                    goal_id = create_macro_release_goal(
                        event_id=event_id,
                        indicator_id=indicator_id,
                        event_data=data,
                        on_complete=lambda iid=indicator_id: _ws_publish_once(None, iid),
                    )
                    logger.info({
                        "event": "phase85_goal_created",
                        "event_id": event_id,
                        "indicator_id": indicator_id,
                    })

                except Exception as exc:
                    raw_preview = str(msg.get("data", ""))[:200]
                    logger.error({
                        "event": "phase85_listener_error",
                        "error": str(exc),
                        "raw": raw_preview,
                    })
                    continue

        except Exception as exc:
            if shutting_down["flag"]:
                break
            logger.warning({
                "event": "phase85_listener_reconnecting",
                "error": str(exc),
            })
            time.sleep(2)
            try:
                pubsub.close()
                r.close()
            except Exception:
                pass
            r = redis_lib.from_url(
                redis_url,
                socket_keepalive=True,
                socket_timeout=None,
            )
            pubsub = r.pubsub()
            pubsub.subscribe(topic)
            continue

    pubsub.close()
    r.close()
    logger.info({"event": "phase85_listener_stopped"})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
