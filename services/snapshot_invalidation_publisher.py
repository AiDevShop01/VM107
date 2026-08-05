"""SnapshotInvalidationPublisher — Django-free VM107-local mirror (Phase 136 Plan 02).

The VM100 publisher
(``VM100/backend/mission_control/services/snapshot_invalidation_publisher.py``)
gates its Redis publish behind a Django ``transaction.on_commit`` hook and also
does a Django-Channels ``group_send``. VM107 has **no Django** — so the emitters'
historic ``try: import transaction / except ImportError: return`` guard silently
no-op'd BEFORE ever reaching a publisher, leaving the ``mission_control``
invalidation path DEAD (Phase 136 SC-2 / D-01).

This module is that path resurrected as a decoupled fire-and-forget:

  * NO Django import anywhere (grep-asserted by the SC-2 gate).
  * Publishes IMMEDIATELY — there is no VM107 DB transaction to hook, so no
    ``transaction.on_commit``.
  * DROPS the VM100 Channels ``group_send`` half entirely — VM100 owns the browser
    relay; VM107 must ONLY publish (no synchronous VM107→VM100 HTTP hop). P4
    cut-coupling preserved.
  * Mirrors the VM100 contract VERBATIM so no emitter call site changes:
      - class name ``SnapshotInvalidationPublisher``
      - constructor ``(redis_client=None, redis_url=None)`` (DI for tests)
      - method ``publish_after_commit(topic, snapshot_id, account_id,
        invalidation_reason="SCHEDULED")``
      - thin payload ``{topic, snapshot_id, generated_at, invalidation_reason}``
      - channel ``mission_control_{account_id}_{topic}``

Env (fail-fast per D-04, mirroring ``initialize.py:31-39`` / ``factory.py:52``):
    VM107_TELEMETRY_REDIS_URL — bare-subscript read; a missing var raises at
    construction (NOT a silent no-op). Same Redis instance as VM107's own
    ``AGENT_TELEMETRY_REDIS_URL`` (see ``agent_telemetry_snapshot_publisher.py:40``).

Leak discipline (T-135-01 / T-136-05): any error log names ``type(e).__name__``
ONLY — never ``str(e)``, host:port, or an IP.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _default_redis_url() -> str:
    """Return the Redis URL from env — fail-fast if absent (D-04 env-lock).

    Bare-subscript (NOT ``.get(..., default)``): a missing
    ``VM107_TELEMETRY_REDIS_URL`` raises ``KeyError`` at construction, surfacing
    the misconfig explicitly rather than degrading to a silent no-op.
    """
    return os.environ["VM107_TELEMETRY_REDIS_URL"]


def _make_thin_payload(
    topic: str,
    snapshot_id: str,
    invalidation_reason: str,
) -> dict:
    """Build the thin invalidation payload dict (mirrors VM100 verbatim)."""
    return {
        "topic": topic,
        "snapshot_id": str(snapshot_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "invalidation_reason": invalidation_reason,
    }


class SnapshotInvalidationPublisher:
    """Publishes thin ``{topic, snapshot_id, generated_at, invalidation_reason}``
    invalidation payloads to Redis pub/sub, IMMEDIATELY (fire-and-forget).

    Constructor:
        redis_client: Optional pre-constructed redis client for dependency
                      injection in tests. When provided, ``redis_url`` is ignored.
        redis_url:    Optional override; defaults to env
                      ``VM107_TELEMETRY_REDIS_URL`` (fail-fast if unset).
    """

    def __init__(
        self,
        redis_client: Optional[object] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        if redis_client is not None:
            # Injected client (tests) — stored as an instance attr so the double
            # actually intercepts calls (class-level monkeypatch would not).
            self._redis = redis_client
        else:
            import redis as _redis_lib

            # redis_url override, else fail-fast env read (bare-subscript, D-04).
            self._redis = _redis_lib.from_url(
                redis_url or _default_redis_url(), decode_responses=True
            )

    def publish_after_commit(
        self,
        topic: str,
        snapshot_id: str,
        account_id: int,
        invalidation_reason: str = "SCHEDULED",
    ) -> None:
        """Publish a thin invalidation event to Redis IMMEDIATELY.

        Name kept as ``publish_after_commit`` for signature-parity with the VM100
        publisher so NO emitter call site changes. VM107 has no DB transaction, so
        despite the name the publish is immediate/fire-and-forget — there is no
        ``transaction.on_commit`` deferral.

        The publish is decoupled (Redis pub/sub only) — no Channels ``group_send``,
        no HTTP hop back to VM100. On a publish exception the error is logged at
        WARN (``type(e).__name__`` only — no host:port/IP leak) and NOT re-raised
        into the caller's persist path.

        :param topic:               Channel topic (e.g. "homepage.global")
        :param snapshot_id:         Id of the snapshot being invalidated
        :param account_id:          Account id scoping the channel
        :param invalidation_reason: Why this invalidation was triggered
        """
        payload = _make_thin_payload(topic, str(snapshot_id), invalidation_reason)
        redis_channel = f"mission_control_{account_id}_{topic}"

        try:
            self._redis.publish(redis_channel, json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 — fire-and-forget, never break caller
            # Leak discipline (T-135-01/T-136-05): class name ONLY, no host:port/IP.
            log.warning(
                "SnapshotInvalidationPublisher: Redis publish failed (%s) — "
                "invalidation not delivered for topic=%s channel=%s",
                type(exc).__name__,
                topic,
                redis_channel,
            )
            return

        # Explicit INFO-on-fire (SC-2: the path is EXPLICIT, never a silent swallow).
        log.info(
            "SnapshotInvalidationPublisher: published invalidation topic=%s "
            "channel=%s reason=%s",
            topic,
            redis_channel,
            invalidation_reason,
        )
