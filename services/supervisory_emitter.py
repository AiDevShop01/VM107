"""Deterministic 4-level supervisory observation emitter (Phase 74 REQ-74-5).

Architecture locks honored:
- Deterministic-only triggers (CONTEXT §19; no LLM in emit path)
- 4 levels: passive | advisory | warning | critical (CONTEXT §20)
- Per-level cooldowns enforced (passive: never emits; advisory: 300s; warning: 120s; critical: 60s)
- Passive NEVER emits Observation to Redis (status-only — CONTEXT §20)
- VM107 NEVER mutates system state — only publishes Observation
- Env-driven cooldowns: SUPERVISORY_COOLDOWN_{ADVISORY,WARNING,CRITICAL}_SEC (fail-fast, no defaults)
- Observation contract from fingpt_core.contracts.observation (cross-VM source of truth)

Trigger catalog (CONTEXT §19):
  1. state_entered(ACTIVE_SUPERVISION)   — initial evaluation → always passive
  2. opportunity_score_changed           — drop_pct vs threshold matrix
  3. structural_break                    — structural_break_severity vs severity ladder
  4. macro_event_in_window               — macro_event_minutes_to_release vs time windows
  5. price_within_X%_of_invalidation     — proximity_pct vs threshold matrix
  6. manual_position_modification        — always advisory

Cooldown state is per-instance (v1 — single VM107 instance per pool member).
v2 TODO: move cooldown state to Redis for multi-instance support (document in SUMMARY).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import yaml

from fingpt_core.contracts.observation import Observation

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────

Level = Literal["passive", "advisory", "warning", "critical"]

LEVEL_TO_SEVERITY = {
    "passive": "INFO",      # passive → INFO (but NEVER emitted)
    "advisory": "INFO",
    "warning": "WARNING",
    "critical": "CRITICAL",
}


# ─────────────────────────────────────────────────────────────────────────────
# TriggerEvent dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TriggerEvent:
    """Phase 74 supervisory trigger event.

    Carries the source DomainEvent backref (trigger_event_id) and discrete
    payload fields per event_type.  No LLM interpretation — all fields are
    deterministically set by the calling code.
    """
    event_type: str                              # one of the 6 TRIGGER_EVENTS
    trigger_event_id: str                        # Phase 56 DomainEvent backref
    account_id: int
    trade_id: Optional[str] = None
    opportunity_id: Optional[str] = None

    # Discrete payload fields (one or more populated per event_type):
    drop_pct: Optional[float] = None             # opportunity_score_changed
    proximity_pct: Optional[float] = None        # price_within_X%_of_invalidation
    structural_break_severity: Optional[str] = None   # structural_break
    macro_event_minutes_to_release: Optional[int] = None  # macro_event_in_window

    # Escalation chain linkage — same correlation_id across passive→advisory→…→critical
    correlation_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# SupervisoryEmitter
# ─────────────────────────────────────────────────────────────────────────────

class SupervisoryEmitter:
    """Deterministic 4-level supervisory observation emitter.

    Usage::

        emitter = SupervisoryEmitter(
            threshold_config_path="config/supervisory_thresholds.yaml"
        )
        obs = emitter.emit(trigger)  # Observation | None (None if passive or cooldown-gated)

    Cooldown state is in-process (per-instance).  Acceptable for v1 with a single
    VM107 instance.  v2 should move to Redis for multi-instance correctness.
    """

    def __init__(
        self,
        threshold_config_path: str,
        _env: dict[str, str] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        threshold_config_path:
            Absolute or relative path to ``supervisory_thresholds.yaml``.
        _env:
            Override dict for env vars (test isolation).  Production passes None
            and reads from ``os.environ``.
        """
        self._env = _env or os.environ
        self._thresholds = self._load_thresholds(threshold_config_path)
        self._cooldown_by_level = self._resolve_cooldowns()
        # Per-level last-emit timestamp (in-process state, v1)
        self._last_emit_by_level: dict[str, datetime] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def emit(
        self,
        trigger: TriggerEvent,
        _at: datetime | None = None,
    ) -> Optional[Observation]:
        """Evaluate trigger deterministically, enforce cooldown, and publish.

        Parameters
        ----------
        trigger:
            TriggerEvent describing what happened (no LLM interpretation).
        _at:
            Override emission timestamp (test injection; production uses UTC now).

        Returns
        -------
        Observation | None
            The emitted Observation, or ``None`` if:
            - level is passive (passive NEVER publishes — CONTEXT §20)
            - level is cooldown-gated (within cooldown window for this level)
        """
        level: Level = self._evaluate_level(trigger)

        now = _at or datetime.now(timezone.utc)

        if self._is_passive_or_gated(level, now):
            return None

        severity = LEVEL_TO_SEVERITY[level]
        obs = Observation(
            category="supervisory",
            severity=severity,
            body=self._format_body(trigger, level),
            generated_at=now,
            source_vm="VM107",
            trigger_event_id=trigger.trigger_event_id,
            correlation_id=trigger.correlation_id or trigger.trigger_event_id,
            trading_impact=(level == "critical"),
            conversation_type=None,
        )

        from services.observation_publisher import publish_observation
        publish_observation(obs)

        self._last_emit_by_level[level] = now
        return obs

    # ── Internal — level evaluation ──────────────────────────────────────────

    def _evaluate_level(self, trigger: TriggerEvent) -> Level:
        """Pure deterministic level evaluation.  NO LLM.  NO randomness."""
        t = trigger.event_type

        # --- 1. Initial evaluation: always passive ---
        if t == "state_entered(ACTIVE_SUPERVISION)":
            return "passive"

        # --- 2. Opportunity score drop ---
        if t == "opportunity_score_changed":
            if trigger.drop_pct is not None:
                thresholds = self._thresholds["opportunity_score_drop_pct"]
                if trigger.drop_pct >= thresholds["critical"]:
                    return "critical"
                if trigger.drop_pct >= thresholds["warning"]:
                    return "warning"
                if trigger.drop_pct >= thresholds["advisory"]:
                    return "advisory"
            return "passive"

        # --- 3. Price proximity to invalidation ---
        if t == "price_within_X%_of_invalidation":
            if trigger.proximity_pct is not None:
                thresholds = self._thresholds["price_proximity_to_invalidation_pct"]
                if trigger.proximity_pct <= thresholds["critical"]:
                    return "critical"
                if trigger.proximity_pct <= thresholds["warning"]:
                    return "warning"
                if trigger.proximity_pct <= thresholds["advisory"]:
                    return "advisory"
            return "passive"

        # --- 4. Structural break ---
        if t == "structural_break":
            if trigger.structural_break_severity is not None:
                thresholds = self._thresholds["structural_break_severity"]
                sev = trigger.structural_break_severity
                if sev == thresholds["critical"]:
                    return "critical"
                if sev == thresholds["warning"]:
                    return "warning"
                # Any other severity maps to advisory
                return "advisory"
            return "passive"

        # --- 5. Macro event in window ---
        if t == "macro_event_in_window":
            minutes = trigger.macro_event_minutes_to_release or 999
            if minutes <= 5:
                return "warning"
            if minutes <= 30:
                return "advisory"
            return "passive"

        # --- 6. Manual position modification ---
        if t == "manual_position_modification":
            return "advisory"

        # Unknown trigger type → passive (safe default)
        log.warning("SupervisoryEmitter: unknown trigger event_type %r → passive", t)
        return "passive"

    def _is_passive_or_gated(self, level: Level, now: datetime) -> bool:
        """Return True if observation should NOT be emitted.

        Passive NEVER emits (CONTEXT §20: 'Status dot only / — / — / —').
        Non-passive levels are gated if within their cooldown window.
        """
        if level == "passive":
            return True  # passive: status-only, never publishes

        last = self._last_emit_by_level.get(level)
        cooldown = self._cooldown_by_level[level]
        if last is None:
            return False  # first emit for this level — allow
        elapsed = (now - last).total_seconds()
        return elapsed < cooldown

    # ── Internal — helpers ───────────────────────────────────────────────────

    def _load_thresholds(self, path: str) -> dict:
        """Load supervisory thresholds YAML."""
        with open(path) as f:
            return yaml.safe_load(f)

    def _resolve_cooldowns(self) -> dict[str, int]:
        """Resolve cooldown seconds from env vars (fail-fast, no defaults)."""
        def _required(key: str) -> int:
            v = self._env.get(key)
            if v is None:
                raise RuntimeError(
                    f"Required env var {key!r} not set — fail-fast "
                    f"(env-driven-no-fallbacks lock, Phase 74)"
                )
            return int(v)

        return {
            "passive": 0,  # never emits — cooldown value unused
            "advisory": _required("SUPERVISORY_COOLDOWN_ADVISORY_SEC"),
            "warning": _required("SUPERVISORY_COOLDOWN_WARNING_SEC"),
            "critical": _required("SUPERVISORY_COOLDOWN_CRITICAL_SEC"),
        }

    def _format_body(self, trigger: TriggerEvent, level: Level) -> str:
        """Deterministic body template — no LLM enrichment in v1 (CONTEXT §19)."""
        trade_str = trigger.trade_id or "-"
        account_str = str(trigger.account_id)
        t = trigger.event_type

        if t == "opportunity_score_changed" and trigger.drop_pct is not None:
            return (
                f"[{level.upper()}] Opportunity score dropped {trigger.drop_pct:.1f}% "
                f"on trade={trade_str} (account={account_str})"
            )
        if t == "price_within_X%_of_invalidation" and trigger.proximity_pct is not None:
            return (
                f"[{level.upper()}] Price within {trigger.proximity_pct:.2f}% of invalidation "
                f"on trade={trade_str} (account={account_str})"
            )
        if t == "structural_break" and trigger.structural_break_severity:
            return (
                f"[{level.upper()}] Structural break ({trigger.structural_break_severity}) "
                f"on trade={trade_str} (account={account_str})"
            )
        if t == "macro_event_in_window":
            mins = trigger.macro_event_minutes_to_release
            return (
                f"[{level.upper()}] Macro event in {mins}m "
                f"on trade={trade_str} (account={account_str})"
            )
        return (
            f"[{level.upper()}] {t} on trade={trade_str} (account={account_str})"
        )
