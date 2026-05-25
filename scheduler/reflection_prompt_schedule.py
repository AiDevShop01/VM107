"""Reflection prompt scheduler — Phase 67 Plan 13 (REQ-67-4).

Event-driven (NOT cron-based — per CONTEXT.md §1: reflection prompts
fire when the trader enters CLOSE state, not on a clock).  The hook
surface is the ``trigger_for_account()`` function — called by:

  1. VM100 ``state_detect_service`` when a CLOSE-state transition is
     detected (Phase 65 wired the transition fan-out; this scheduler
     ships the listener).
  2. Operator-level cron sweeps as a safety net (catches accounts that
     missed the transition signal due to WS / network blips).

For each opted-in account, builds a ReflectionPromptSetContract via
``ReflectionPromptEmitter.get_reflection_prompts()`` and routes through
``persist_and_publish()`` so the WS topic
``mission_control.close.journal_prompts`` fires AFTER snapshot commit.

Per-account isolation (Pitfall 7 parallel):
  Each account is wrapped in try/except.  A single failure logs +
  appends to the failures list; the loop CONTINUES so a degraded
  upstream for one account does not blackout the entire fleet.

Per Phase 47.3 lock — env-driven config:
  ``VM107_REFLECTION_PROMPT_TRIGGER`` env var is REQUIRED in
  ``docker-compose.yml`` (label-only — value documents the trigger
  source for ops visibility; the actual event arrives via the
  state-detect signal, not a cron expression).
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_cls, datetime, timezone
from typing import Iterable

log = logging.getLogger(__name__)


SCHEDULER_NAME = "reflection_prompt_schedule"
TOPIC = "mission_control.close.journal_prompts"


def _resolve_opted_in_accounts() -> Iterable[int]:
    """Return the iterable of account_ids opted into reflection prompts.

    Mirrors the other Phase 67 schedulers.  Reads
    ``VM107_REFLECTION_PROMPT_ACCOUNT_IDS`` env var (comma-separated ints).
    Empty / unset → empty iterator → scheduler is a no-op.
    """
    raw = os.environ.get("VM107_REFLECTION_PROMPT_ACCOUNT_IDS", "")
    if not raw.strip():
        return []
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            log.warning(
                "reflection_prompt_schedule.bad_account_id",
                extra={"raw": token},
            )
    return out


def trigger_for_account(
    account_id: int,
    session_date: date_cls | None = None,
    trigger_reason: str = "STATE_CLOSE_TRANSITION",
) -> dict:
    """Event-driven hook for a single account entering CLOSE state.

    Args:
        account_id: Account that just transitioned to CLOSE.
        session_date: Optional override (defaults to today UTC).
        trigger_reason: Label for observability (state-detect vs. cron).

    Returns:
        Per-account result dict with ``account_id`` + ``status`` +
        optional ``exc_type``.
    """
    session_date = session_date or datetime.now(timezone.utc).date()
    try:
        from emitters.reflection_prompt_emitter import ReflectionPromptEmitter
    except ImportError as exc:
        log.error(
            "reflection_prompt_schedule.emitter_import_failed",
            extra={"exc_type": type(exc).__name__, "exc": str(exc)},
        )
        return {
            "account_id": account_id,
            "status": "import_error",
            "exc_type": type(exc).__name__,
            "exc": str(exc),
        }

    emitter = ReflectionPromptEmitter()
    try:
        prompt_set = emitter.get_reflection_prompts(
            account_id=account_id, session_date=session_date
        )
        emitter.persist_and_publish(
            prompt_set, invalidation_reason=trigger_reason
        )
        log.info(
            "reflection_prompt_schedule.account_succeeded",
            extra={
                "account_id": account_id,
                "session_date": session_date.isoformat(),
                "trigger_reason": trigger_reason,
            },
        )
        return {"account_id": account_id, "status": "ok"}
    except Exception as exc:  # noqa: BLE001 — per-account isolation
        log.warning(
            "reflection_prompt_schedule.account_failed",
            extra={
                "account_id": account_id,
                "session_date": session_date.isoformat(),
                "trigger_reason": trigger_reason,
                "exc_type": type(exc).__name__,
                "exc": str(exc),
            },
        )
        return {
            "account_id": account_id,
            "status": "failed",
            "exc_type": type(exc).__name__,
        }


def run_once(
    account_ids: Iterable[int] | None = None,
    session_date: date_cls | None = None,
    trigger_reason: str = "CRON_SWEEP",
) -> dict:
    """Execute a single sweep tick across all opted-in accounts.

    Used as the cron-safety-net path.  The real-time path is
    ``trigger_for_account()`` invoked from state-detect.

    Args:
        account_ids: Override the opt-in account resolver (used by tests).
        session_date: Optional override (defaults to today UTC).
        trigger_reason: Label for observability.

    Returns:
        A summary dict with succeeded / failed account_id lists.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    if account_ids is None:
        account_ids = _resolve_opted_in_accounts()

    succeeded: list[int] = []
    failed: list[dict] = []
    for account_id in account_ids:
        result = trigger_for_account(
            account_id=account_id,
            session_date=session_date,
            trigger_reason=trigger_reason,
        )
        if result.get("status") == "ok":
            succeeded.append(account_id)
        else:
            failed.append(
                {
                    "account_id": account_id,
                    "exc_type": result.get("exc_type", "unknown"),
                }
            )

    summary = {
        "scheduler": SCHEDULER_NAME,
        "topic": TOPIC,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "succeeded": succeeded,
        "failed": failed,
        "skipped_count": 0,
    }
    log.info("reflection_prompt_schedule.sweep_complete", extra=summary)
    return summary


__all__ = ["run_once", "trigger_for_account", "SCHEDULER_NAME", "TOPIC"]
