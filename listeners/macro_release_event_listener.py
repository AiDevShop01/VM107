"""Phase 83 release-event subscriber → Brain goal fan-out (Phase 85 Plan 10).

Subscribes to the ``macro.release_events`` Redis Pub/Sub channel.
On each well-formed message, calls ``create_macro_release_goal`` which creates a
``macro_release_analysis`` Brain goal and fans out 3 child tasks:

  1. vm107.macro_release_analyst         (no deps — fires immediately)
  2. vm107.macro_asset_exposure_analyst  (no deps — fires in parallel)
  3. vm107.macro_executive_summary_writer (depends on 1 + 2 — fires after both)

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
    "source": "vm101.macro_calendar"
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

from core.scheduling.macro_release_goal import (
    configure_default_orchestrator,
    create_macro_release_goal,
)
from core.scheduling.orchestrator_factory import build_default_orchestrator

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

                    create_macro_release_goal(
                        event_id=event_id,
                        indicator_id=indicator_id,
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
