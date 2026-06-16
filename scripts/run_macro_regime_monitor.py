"""Phase 87 Plan 10 (Wave 5b) — long-running macro_regime_monitor runner.

Long-running APScheduler ``BlockingScheduler`` that fires
``MacroRegimeMonitor.run_once()`` once every 6 hours UTC (cron
``0 */6 * * *``). Ships as the docker-compose sibling service
``vm107-macro-regime-monitor`` per LOCK-8 / REQ-87-8 /
``feedback_mgmt_commands_need_compose_service``. Plan 74-03 lost the
observation pipeline by skipping this lock; Plan 87-10 honours it from
day one (alongside Plan 87-08's vm107-macro-story-tracker in the same
docker-compose.yml).

Run locally / inside the sibling service::

    python -m scripts.run_macro_regime_monitor

Restart after env changes (NEVER use ``docker restart`` — it ignores
``env_file`` edits)::

    docker compose up -d --force-recreate --no-deps vm107-macro-regime-monitor

Env vars required (fail-fast; no ``os.getenv("X", "default")`` patterns
per CLAUDE.md ``env-driven-no-fallbacks`` lock):

    BELIEF_STORE_POSTGRES_URL  — Plan 87-09 BeliefStore (read+write)
    BELIEF_STORE_MONGO_URL     — Plan 87-09 BeliefStore cache + TTL
    PHASE74_DISPATCHER_URL     — Phase 74 NotificationDispatcher base URL
    VM101_INTERNAL_BASE_URL    — VM101 typed economic_event API base URL

Deviation from Plan 87-10 reference implementation (Rule 3 Blocking):
The plan specified ``VM107/management/commands/run_macro_regime_monitor.py``
(Django management command). VM107 has NO Django (no ``manage.py``, no
``settings.py``, no Django apps). Adapted to the in-repo
``python -m scripts.*`` CLI pattern matching Plan 87-08's
``scripts/run_macro_story_tracker.py`` precedent. Same env-driven
fail-fast surface; same observable side effects.
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Where the healthcheck reads the last-successful-tick timestamp.
# ``/app/logs`` is the canonical container path; the sibling-service
# compose definition mounts the host ``./logs`` directory there.
LAST_RUN_FILE = pathlib.Path("/app/logs/macro_regime_monitor_last_run.iso")


def _env_required(key: str) -> str:
    """Return env var value or exit(1). No fallback defaults."""
    value = os.environ.get(key)
    if not value:
        sys.stderr.write(
            f"ERROR: env var {key} required (CLAUDE.md "
            "env-driven-no-fallbacks lock — no default)\n"
        )
        sys.exit(1)
    return value


def _build_monitor():
    """Wire the MacroRegimeMonitor against real collaborators.

    Imports happen INSIDE the function so the test suite (which never
    calls ``main``) does not have to import the heavy modules.
    """
    from agents.macro_regime_monitor.agent import MacroRegimeMonitor
    from agents.macro_regime_monitor.phase74_notification_client import (
        Phase74NotificationClient,
    )
    from agents.macro_story_tracker.release_poller import ReleasePoller
    from core.belief.belief_store import BeliefStore

    # Optional collaborators that land at deploy time alongside the
    # sibling service. Import lazily so a missing optional module on the
    # dev box does not crash the CLI before the operator sees the env-var
    # fail-fast message.
    event_store = _import_event_store()
    classifications = _import_classification_repo()

    return MacroRegimeMonitor(
        belief_store=BeliefStore(),
        anchor_release_poller=ReleasePoller(),
        event_store=event_store,
        phase74_client=Phase74NotificationClient(),
        classification_repo=classifications,
    )


def _import_event_store():
    """Phase 56 event store handle."""
    try:
        from core.runtime import event_store  # type: ignore[import]
        return event_store
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "core.runtime.event_store not importable — Plan 87-14 deploy "
            "gate must wire the Phase 56 event store before the sibling "
            "service can run."
        ) from exc


def _import_classification_repo():
    """VM101 macro_regime_classification DAL."""
    try:
        from persistence.macro_regime_classification_repo import (  # type: ignore[import]
            MacroRegimeClassificationRepo,
        )
        return MacroRegimeClassificationRepo()
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "persistence.macro_regime_classification_repo.MacroRegimeClassificationRepo "
            "not importable — Plan 87-14 deploy gate must wire the "
            "VM101 macro_regime_classification DAL."
        ) from exc


def _record_last_run() -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(tz=timezone.utc).isoformat())


def _run_tick(monitor) -> None:
    """Execute one tick, write the heartbeat, log the stats. Never raise."""
    try:
        stats = monitor.run_once()
        _record_last_run()
        logger.info({"event": "macro_regime_monitor_tick", **stats})
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            {"event": "macro_regime_monitor_tick_failed",
             "error": str(exc)}
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Fail-fast on required env BEFORE wiring expensive collaborators.
    _env_required("BELIEF_STORE_POSTGRES_URL")
    _env_required("BELIEF_STORE_MONGO_URL")
    _env_required("PHASE74_DISPATCHER_URL")
    _env_required("VM101_INTERNAL_BASE_URL")

    from apscheduler.schedulers.blocking import BlockingScheduler

    monitor = _build_monitor()
    sched = BlockingScheduler(timezone="UTC")

    sched.add_job(
        _run_tick,
        trigger="cron",
        hour="*/6",
        minute=0,
        kwargs={"monitor": monitor},
        id="macro_regime_monitor_6h",
        max_instances=1,
        coalesce=True,
    )

    # Run an immediate first tick so the healthcheck has a valid
    # heartbeat before the cron fires. Without this the sibling service
    # flaps unhealthy for ≤7 hours on first boot.
    logger.info({"event": "macro_regime_monitor_starting"})
    _run_tick(monitor)

    sched.start()


if __name__ == "__main__":  # pragma: no cover — exercised by the sibling service
    main()
