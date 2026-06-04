"""Phase 83 Plan 10 — Decision G2 snapshot persistence (Postgres truth + Redis cache).

Two clients for the two G2 persistence tiers:
  SnapshotHTTPWriter  — POST to VM100 /api/v1/mission-control/snapshots/macro (truth)
  SnapshotRedisCache  — Redis key macro_emitter:latest:{state} TTL 60s (hot path)

Both are injected into MacroEmitterLoop so tests can mock them independently.

Env-driven config (CLAUDE.md lock — no fallback defaults for required vars):
  MACRO_EMITTER_SNAPSHOT_URL   — required: base URL of VM100 (e.g. http://vm100-backend:8000)
  VM107_SERVICE_JWT             — required: HS256 bearer token for JWTAuth gate
  MACRO_EMITTER_REDIS_URL       — required: Redis connection URL
  MACRO_EMITTER_CACHE_TTL_SEC   — optional: cache TTL in seconds (default 60)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx
import redis

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fail-fast module-level env validation (CLAUDE.md env-driven-config lock).
# These are read at import time so missing vars fail-fast at process startup,
# not silently at first write (which might be minutes into a cadence tick).
# ---------------------------------------------------------------------------
_SNAPSHOT_URL: str = os.environ["MACRO_EMITTER_SNAPSHOT_URL"]
_JWT: str = os.environ["VM107_SERVICE_JWT"]
_REDIS_URL: str = os.environ["MACRO_EMITTER_REDIS_URL"]
_CACHE_TTL_SEC: int = int(os.environ.get("MACRO_EMITTER_CACHE_TTL_SEC", "60"))


# ---------------------------------------------------------------------------
# SnapshotHTTPWriter — G2 truth write (Postgres via VM100 HTTP endpoint)
# ---------------------------------------------------------------------------


class SnapshotHTTPWriter:
    """G2 truth write — POST ToolResultEnvelope to VM100 macro_emitter_snapshots.

    Raises on non-2xx responses (caller handles for Tier-3 degradation).
    Constructor args allow test injection without reloading the module.
    """

    def __init__(
        self,
        url: str = _SNAPSHOT_URL,
        jwt: str = _JWT,
        timeout: float = 10.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._jwt = jwt
        self._timeout = timeout

    def write(self, envelope, state: str, refresh_reason: str) -> int:
        """POST envelope payload to VM100 Postgres truth-write endpoint.

        Args:
            envelope: ToolResultEnvelope[MacroEmissionPayload] from composer.
            state: Current market state (PRE | OPEN | ACTIVE_SUPERVISION | etc.)
            refresh_reason: cadence | interrupt | manual | startup

        Returns:
            Integer row id of created MacroEmitterSnapshot.

        Raises:
            httpx.HTTPStatusError: on non-2xx VM100 response (let caller degrade).
        """
        now = datetime.now(timezone.utc).isoformat()

        # Support both Pydantic v1 (.dict()) and v2 (.model_dump()).
        # mode='json' coerces UUID/datetime/etc. into JSON-safe primitives.
        payload_dict = (
            envelope.model_dump(mode="json")
            if hasattr(envelope, "model_dump")
            else envelope.dict()
        )

        # Extract provenance fields (AgentEnvelope contract — Phase 70.5)
        provenance = getattr(envelope, "provenance", {}) or {}

        body = {
            "state": state,
            "payload_jsonb": payload_dict,
            "registry_snapshot_hash": provenance.get("registry_snapshot_hash", "unknown"),
            "novelty_score_jsonb": None,  # composer embeds per-item novelty in payload
            "prompt_version": provenance.get("prompt_version", "unknown"),
            "model_version": provenance.get("model_version", "unknown"),
            "refresh_reason": refresh_reason,
            "generated_at": provenance.get("generated_at", now),
            "next_refresh_at": None,
        }

        response = httpx.post(
            f"{self._url}/api/v1/mission-control/snapshots/macro",
            json=body,
            headers={"Authorization": f"Bearer {self._jwt}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["id"]


# ---------------------------------------------------------------------------
# SnapshotRedisCache — G2 hot path (Redis key macro_emitter:latest:{state})
# ---------------------------------------------------------------------------


class SnapshotRedisCache:
    """G2 hot path — Redis key macro_emitter:latest:{state} with TTL.

    Degraded writes (Redis unavailable) log a warning and continue silently —
    the hot path is best-effort; Postgres is the truth store.
    Constructor args allow test injection (inject a fakeredis client).
    """

    def __init__(
        self,
        url: str = _REDIS_URL,
        ttl_sec: int = _CACHE_TTL_SEC,
    ) -> None:
        self._client = redis.Redis.from_url(url)
        self._ttl = ttl_sec

    def write(self, envelope, state: str) -> None:
        """Write envelope to Redis cache key macro_emitter:latest:{state}.

        Logs a warning on Redis error (never raises — hot path is best-effort).
        """
        key = f"macro_emitter:latest:{state}"
        # Support both Pydantic v1 and v2 (mode='json' makes UUIDs/datetimes JSON-safe)
        value = (
            json.dumps(envelope.model_dump(mode="json"))
            if hasattr(envelope, "model_dump")
            else envelope.json()
        )
        try:
            self._client.setex(key, self._ttl, value)
        except redis.RedisError as exc:
            log.warning(
                "SnapshotRedisCache.write degraded (state=%s): %r — hot path skipped",
                state, exc,
            )

    def read(self, state: str) -> dict | None:
        """Read cache key macro_emitter:latest:{state}.

        Returns:
            Deserialized dict, or None if key missing / Redis unavailable.
        """
        key = f"macro_emitter:latest:{state}"
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except (redis.RedisError, ValueError, json.JSONDecodeError) as exc:
            log.warning(
                "SnapshotRedisCache.read degraded (state=%s): %r",
                state, exc,
            )
            return None
