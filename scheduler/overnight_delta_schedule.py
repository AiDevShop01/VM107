"""Overnight delta scheduler — Phase 67 Plan 13 (REQ-67-3).

Iterates the opt-in account list, builds an OvernightDeltaContract via
``OvernightDeltaEmitter.get_overnight_delta()`` for each account, and
routes through ``persist_and_publish()`` so the WS topic
``mission_control.pre.overnight_delta`` fires AFTER snapshot commit.

Cron schedule (env-driven):
  ``VM107_OVERNIGHT_DELTA_CRON`` (typical: ``30 6 * * *`` — 06:30 UTC daily)

Per-account isolation (Pitfall 7 parallel):
  Each account is wrapped in try/except.  A single failure logs +
  appends to the failures list; the loop CONTINUES so a degraded
  upstream for one account does not blackout the entire fleet.

Per Phase 47.3 lock — env-driven config / no fallback defaults:
  ``VM107_OVERNIGHT_DELTA_CRON`` env var is REQUIRED to be set in
  ``docker-compose.yml`` (fail-fast at startup, not at first invocation).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable

log = logging.getLogger(__name__)


SCHEDULER_NAME = "overnight_delta_schedule"
TOPIC = "mission_control.pre.overnight_delta"


def _resolve_opted_in_accounts() -> Iterable[int]:
    """Return the iterable of account_ids opted into overnight delta.

    Mirrors ``morning_brief_schedule._resolve_opted_in_accounts``.  Reads
    ``VM107_OVERNIGHT_DELTA_ACCOUNT_IDS`` env var (comma-separated ints).
    Empty / unset → empty iterator → scheduler is a no-op.
    """
    raw = os.environ.get("VM107_OVERNIGHT_DELTA_ACCOUNT_IDS", "")
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
                "overnight_delta_schedule.bad_account_id",
                extra={"raw": token},
            )
    return out


def run_once(account_ids: Iterable[int] | None = None) -> dict:
    """Execute a single scheduler tick.

    Args:
        account_ids: Override the opt-in account resolver (used by tests).

    Returns:
        A summary dict with succeeded / failed account_id lists.
    """
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        from emitters.overnight_delta_emitter import OvernightDeltaEmitter
    except ImportError as exc:
        log.error(
            "overnight_delta_schedule.emitter_import_failed",
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

    emitter = OvernightDeltaEmitter()
    succeeded: list[int] = []
    failed: list[dict] = []

    for account_id in account_ids:
        try:
            delta = emitter.get_overnight_delta(account_id)
            emitter.persist_and_publish(delta, invalidation_reason="SCHEDULED")
            succeeded.append(account_id)
        except Exception as exc:  # noqa: BLE001 — per-account isolation
            log.warning(
                "overnight_delta_schedule.account_failed",
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
    log.info("overnight_delta_schedule.tick_complete", extra=summary)
    return summary


__all__ = ["run_once", "SCHEDULER_NAME", "TOPIC"]
