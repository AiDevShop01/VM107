"""
Hybrid agent telemetry — real activity + heartbeat fallback (CONTEXT.md §5).

Two event types:
  - REAL_ACTIVITY  : when an agent does substantive work
  - HEARTBEAT_IDLE : synthetic alive-ping (NEVER counts toward productivity)

Always distinguishable in payload. Heartbeats NEVER count toward productivity metrics.

Publishes to Redis channel: vm107.agent_telemetry (REQ-66-4 lock).
If Redis is not configured, events are returned in-memory (test / offline mode).

All 14 locked agent IDs from REQ-66-4 / CONTEXT.md §5 are supported.
Forbidden anthropomorphic phrases are rejected at emit time.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from emitters.heartbeat_phrasing import FORBIDDEN_PHRASES, get_phrasing

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_NAME = "vm107.agent_telemetry"  # LOCKED per REQ-66-4
HEARTBEAT_IDLE_THRESHOLD_SECONDS = 60

# 14 locked agent IDs — REQ-66-4 / CONTEXT.md §5
LOCKED_AGENT_IDS: frozenset[str] = frozenset({
    "macro-agent",
    "briefing-agent",
    "calendar-agent",
    "liquidity-agent",
    "readiness-agent",
    "pattern-engine",
    "attention-engine",
    "risk-agent",
    "session-agent",
    "replay-engine",
    "embeddings",
    "behavior-agent",
    "journal-agent",
    "discovery-agent",
})

# Agents expected online by state — heartbeats only fire for these
EXPECTED_ONLINE_BY_STATE: dict[str, frozenset[str]] = {
    "pre": frozenset({
        "macro-agent", "briefing-agent", "calendar-agent",
        "readiness-agent", "session-agent",
    }),
    "open": frozenset({
        "macro-agent", "briefing-agent", "pattern-engine", "liquidity-agent",
        "risk-agent", "attention-engine", "session-agent", "behavior-agent",
    }),
    "mid": frozenset({
        "pattern-engine", "risk-agent", "attention-engine",
        "behavior-agent", "journal-agent", "discovery-agent", "replay-engine",
    }),
    "close": frozenset({
        "journal-agent", "discovery-agent", "embeddings", "replay-engine",
    }),
}


# ─────────────────────────────────────────────────────────────────────────────
# Event object (lightweight — mirrors AgentTelemetryEvent contract shape)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TelemetryEventPayload:
    """Lightweight telemetry event carrier.

    Mirrors the AgentTelemetryEvent Pydantic contract shape so downstream
    consumers can use it interchangeably (duck-typing safe).
    """
    event_id: str
    agent_id: str
    event_type: str          # "REAL_ACTIVITY" | "HEARTBEAT_IDLE"
    state: str
    summary: str
    activity: str            # same content as summary; exposed for test assertions
    generated_at: datetime
    degraded_mode: bool = False
    account_id: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# MetricCollector
# ─────────────────────────────────────────────────────────────────────────────


class MetricCollector:
    """Productivity metric collector.

    Counts REAL_ACTIVITY events per agent. Skips HEARTBEAT_IDLE events —
    they MUST NOT increment productivity metrics (REQ-66-4).
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, event: TelemetryEventPayload) -> None:
        """Record an event. HEARTBEAT_IDLE events are silently skipped."""
        if event.event_type == "HEARTBEAT_IDLE":
            return  # heartbeats NEVER count toward productivity
        agent_id = event.agent_id
        self._counts[agent_id] = self._counts.get(agent_id, 0) + 1

    def get_activity_count(self, agent_id: str) -> int:
        """Return the REAL_ACTIVITY count for the given agent (heartbeats excluded)."""
        return self._counts.get(agent_id, 0)


# ─────────────────────────────────────────────────────────────────────────────
# AgentTelemetryEmitter
# ─────────────────────────────────────────────────────────────────────────────


class AgentTelemetryEmitter:
    """Hybrid agent telemetry emitter — real activity + heartbeat model.

    Publishes to Redis channel `vm107.agent_telemetry` (REQ-66-4 lock).
    Falls back to in-memory mode when Redis is not configured (test / offline).

    Usage::

        emitter = AgentTelemetryEmitter()
        event = emitter.emit_real_activity(
            agent_id="risk-agent",
            activity="Computed beta against DXY benchmark",
            state="mid",
        )
        # event.event_type == "REAL_ACTIVITY"
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        """Initialize emitter. Redis is optional — falls back to in-memory mode.

        Args:
            redis_url: Redis URL. When None, reads VM107_TELEMETRY_REDIS_URL env var.
                       Falls back to in-memory (no-op publish) if unset.
        """
        self._redis = None
        self._published_events: list[TelemetryEventPayload] = []  # in-memory store for tests

        import os
        _url = redis_url or os.getenv("VM107_TELEMETRY_REDIS_URL")
        if _url:
            try:
                import redis as redis_lib
                self._redis = redis_lib.from_url(_url, decode_responses=True)
            except Exception as exc:
                log.warning(
                    "AgentTelemetryEmitter: Redis unavailable, falling back to in-memory: %s", exc
                )

    # ── Public API ──────────────────────────────────────────────────────────

    def emit_real_activity(
        self,
        agent_id: str,
        activity: str,
        state: str,
        account_id: Optional[int] = None,
    ) -> TelemetryEventPayload:
        """Emit a REAL_ACTIVITY telemetry event.

        Raises ValueError if agent_id is not in the 14 locked IDs or if
        activity text contains a forbidden anthropomorphic phrase.

        Args:
            agent_id:   One of the 14 locked agent IDs (REQ-66-4).
            activity:   Human-readable description of what the agent did.
            state:      Current trading session state.
            account_id: Account scope (optional for non-account-scoped agents).

        Returns:
            TelemetryEventPayload with event_type="REAL_ACTIVITY".
        """
        self._guard_agent_id(agent_id)
        self._guard_forbidden_phrases(activity)

        event = TelemetryEventPayload(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            event_type="REAL_ACTIVITY",
            state=state,
            summary=activity,
            activity=activity,
            generated_at=datetime.now(timezone.utc),
            degraded_mode=False,
            account_id=account_id,
        )
        self._publish(event)
        return event

    def emit_heartbeat(
        self,
        agent_id: str,
        state: str,
        iteration: int = 0,
        account_id: Optional[int] = None,
    ) -> TelemetryEventPayload:
        """Emit a HEARTBEAT_IDLE telemetry event.

        Heartbeats MUST NOT count toward productivity metrics downstream.
        Phrasing is pulled from HEARTBEAT_PHRASINGS registry for (agent_id, state).

        Args:
            agent_id:  One of the 14 locked agent IDs.
            state:     Current trading session state.
            iteration: Rotation index for phrasing variation.
            account_id: Account scope (optional).

        Returns:
            TelemetryEventPayload with event_type="HEARTBEAT_IDLE".
        """
        self._guard_agent_id(agent_id)
        summary = get_phrasing(agent_id, state, iteration=iteration)
        self._guard_forbidden_phrases(summary)

        event = TelemetryEventPayload(
            event_id=str(uuid.uuid4()),
            agent_id=agent_id,
            event_type="HEARTBEAT_IDLE",
            state=state,
            summary=summary,
            activity=summary,
            generated_at=datetime.now(timezone.utc),
            degraded_mode=False,
            account_id=account_id,
        )
        self._publish(event)
        return event

    def should_emit_heartbeat(
        self,
        agent_id: str,
        state: str,
        last_activity_at: datetime,
        agent_online: bool,
    ) -> bool:
        """Determine whether a heartbeat should fire for this agent.

        Heartbeat fires ONLY when ALL conditions are met:
          1. agent_online is True
          2. state is in EXPECTED_ONLINE_BY_STATE (active operational state)
          3. agent_id is in the expected-online set for the current state
          4. time since last_activity_at > HEARTBEAT_IDLE_THRESHOLD_SECONDS (60s)

        Args:
            agent_id:         Agent to check.
            state:            Current trading session state.
            last_activity_at: When the agent last emitted REAL_ACTIVITY.
            agent_online:     Whether the agent is expected/confirmed online.

        Returns:
            True if heartbeat should fire; False otherwise.
        """
        if not agent_online:
            return False

        state_lower = state.lower()
        expected = EXPECTED_ONLINE_BY_STATE.get(state_lower)
        if expected is None:
            return False  # inactive state — no heartbeats

        if agent_id not in expected:
            return False  # agent not expected online in this state

        now = datetime.now(timezone.utc)
        last_at = last_activity_at
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        idle_seconds = (now - last_at).total_seconds()
        return idle_seconds > HEARTBEAT_IDLE_THRESHOLD_SECONDS

    # ── Internal helpers ────────────────────────────────────────────────────

    def _publish(self, event: TelemetryEventPayload) -> None:
        """Publish event to Redis channel `vm107.agent_telemetry` (REQ-66-4 lock).

        Falls back to in-memory storage when Redis is unavailable.
        """
        import json as _json

        payload = {
            "event_id": event.event_id,
            "agent_id": event.agent_id,
            "event_type": event.event_type,
            "state": event.state,
            "summary": event.summary,
            "activity": event.activity,
            "generated_at": event.generated_at.isoformat(),
            "degraded_mode": event.degraded_mode,
            "account_id": event.account_id,
        }
        self._published_events.append(event)  # always stored in-memory (for tests)

        if self._redis is not None:
            try:
                self._redis.publish(CHANNEL_NAME, _json.dumps(payload))
            except Exception as exc:
                log.warning(
                    "AgentTelemetryEmitter._publish: Redis publish failed: %s", exc
                )

    def _guard_agent_id(self, agent_id: str) -> None:
        """Raise ValueError if agent_id is not one of the 14 locked IDs."""
        if agent_id not in LOCKED_AGENT_IDS:
            raise ValueError(
                f"Unknown agent_id {agent_id!r}. Must be one of the 14 locked agent IDs "
                f"(REQ-66-4). Locked IDs: {sorted(LOCKED_AGENT_IDS)}"
            )

    def _guard_forbidden_phrases(self, text: str) -> None:
        """Raise ValueError if text contains any forbidden anthropomorphic phrase."""
        text_lower = text.lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in text_lower:
                raise ValueError(
                    f"Forbidden anthropomorphic phrase in telemetry text: {phrase!r}. "
                    f"Use operational, terse language that describes what the agent DID, "
                    f"not what it is 'thinking' or 'feeling'."
                )
