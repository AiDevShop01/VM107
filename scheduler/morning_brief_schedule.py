"""Morning brief scheduler — Phase 67 Plan 13 (REQ-67-3).

Iterates the opt-in account list, builds a MorningBriefContract via
``MorningBriefEmitter.get_morning_brief()`` for each account, and routes
through ``persist_and_publish()`` so the WS topic
``mission_control.pre.morning_brief`` fires AFTER snapshot commit.

Cron schedule (env-driven):
  ``VM107_MORNING_BRIEF_CRON`` (typical: ``0 7 * * *`` — 07:00 UTC daily)

Per-account isolation (Pitfall 7 parallel):
  Each account is wrapped in try/except.  A single failure logs +
  appends to the failures list; the loop CONTINUES so a degraded
  upstream for one account does not blackout the entire fleet.

Per Phase 47.3 lock — env-driven config / no fallback defaults:
  ``VM107_MORNING_BRIEF_CRON`` env var is REQUIRED to be set in
  ``docker-compose.yml`` (fail-fast at startup, not at first invocation).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable

log = logging.getLogger(__name__)


SCHEDULER_NAME = "morning_brief_schedule"
TOPIC = "mission_control.pre.morning_brief"


def _resolve_opted_in_accounts() -> Iterable[int]:
    """Return the iterable of account_ids opted into morning brief.

    Phase 67 v1 — Plan 13 ships the scheduler scaffold; the opt-in
    registry surface lives in Phase 68+ (user-settings table).  Until
    that lands the resolver defers to an env-driven account list:

        VM107_MORNING_BRIEF_ACCOUNT_IDS="42,84,168"

    Empty / unset → empty iterator → scheduler is a no-op.  This keeps
    the scheduler safe to wire up before the opt-in surface exists.
    """
    raw = os.environ.get("VM107_MORNING_BRIEF_ACCOUNT_IDS", "")
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
                "morning_brief_schedule.bad_account_id",
                extra={"raw": token},
            )
    return out


def run_once(account_ids: Iterable[int] | None = None) -> dict:
    """Execute a single scheduler tick.

    Args:
        account_ids: Override the opt-in account resolver (used by tests).

    Returns:
        A summary dict::

            {
                "scheduler": "morning_brief_schedule",
                "started_at": "<iso8601>",
                "finished_at": "<iso8601>",
                "succeeded": [42, 84],
                "failed": [{"account_id": 168, "exc_type": "TimeoutError"}],
                "skipped_count": 0,
            }

        The summary is the canonical observable surface — Dagster /
        cron / pytest all inspect this shape.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    # Late-import the emitter so test environments without VM107 deps
    # can still import the scheduler module.
    try:
        from emitters.morning_brief_emitter import MorningBriefEmitter
    except ImportError as exc:
        log.error(
            "morning_brief_schedule.emitter_import_failed",
            extra={"exc_type": type(exc).__name__, "exc": str(exc)},
        )
        return {
            "scheduler": SCHEDULER_NAME,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "succeeded": [],
            "failed": [],
            "skipped_count": 0,
            "import_error": str(exc),
        }

    if account_ids is None:
        account_ids = _resolve_opted_in_accounts()

    emitter = MorningBriefEmitter()
    succeeded: list[int] = []
    failed: list[dict] = []

    for account_id in account_ids:
        try:
            brief = emitter.get_morning_brief(account_id)
            emitter.persist_and_publish(brief, invalidation_reason="SCHEDULED")
            succeeded.append(account_id)
        except Exception as exc:  # noqa: BLE001 — per-account isolation
            log.warning(
                "morning_brief_schedule.account_failed",
                extra={
                    "account_id": account_id,
                    "exc_type": type(exc).__name__,
                    "exc": str(exc),
                },
            )
            failed.append(
                {"account_id": account_id, "exc_type": type(exc).__name__}
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
    log.info("morning_brief_schedule.tick_complete", extra=summary)
    return summary


__all__ = ["run_once", "SCHEDULER_NAME", "TOPIC"]
