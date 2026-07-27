"""Phase 87 Wave 4b — long-running macro_story_tracker runner.

Long-running APScheduler ``BlockingScheduler`` that fires the
``MacroStoryTracker.run_once()`` tick once per hour at minute 5 UTC.
Ships as the docker-compose sibling service ``vm107-macro-story-tracker``
per LOCK-8 / REQ-87-8 / ``feedback_mgmt_commands_need_compose_service``.
Plan 74-03 lost the observation pipeline by skipping this lock; Plan
87-08 honours it from day one.

Run locally / inside the sibling service::

    python -m scripts.run_macro_story_tracker

Restart after env changes (NEVER use ``docker restart`` — it ignores
``env_file`` edits)::

    docker compose up -d --force-recreate --no-deps vm107-macro-story-tracker

Env vars required (fail-fast; no ``os.getenv("X", "default")`` patterns
per CLAUDE.md ``env-driven-no-fallbacks`` lock):

    VM101_INTERNAL_BASE_URL  — e.g., http://192.168.1.201:8001
    QDRANT_URL               — e.g., http://192.168.1.151:6333

Deviation from Plan 87-08 reference implementation (Rule 3 Blocking):
The plan specified ``VM107/management/commands/run_macro_story_tracker.py``
(Django management command). VM107 has NO Django (no ``manage.py``, no
``settings.py``, no Django apps). Adapted to the in-repo
``python -m scripts.*`` CLI pattern — mirrors ``scripts/load_macro_graph_seed.py``
+ ``scripts/migrate_faiss_to_qdrant.py`` + ``scripts/backfill_macro_episodes.py``
(the Phase 87-07 precedent). Same env-driven fail-fast surface; same
observable side effects.
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
LAST_RUN_FILE = pathlib.Path("/app/logs/macro_story_tracker_last_run.iso")


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


def _build_tracker():
    """Wire the MacroStoryTracker against real collaborators.

    Imports happen INSIDE the function so the test suite (which never
    calls ``main``) does not have to import the heavy modules.
    """
    from agents.macro_story_tracker.agent import MacroStoryTracker
    from agents.macro_story_tracker.release_poller import ReleasePoller
    from core.memory.episodic_memory_service import EpisodicMemoryService
    from core.memory.message_loop_prompts_before_b6 import (
        message_loop_prompts_before_b6,
    )

    # Embedding + LLM + envelope + persist + ws collaborators land at deploy
    # time alongside the sibling-service ConfigMap. Import lazily so a
    # missing optional module on the dev box does not crash the CLI before
    # the operator sees the env-var fail-fast message.
    embedding_service = _import_embedding_service()
    llm_router = _import_llm_router()
    envelope_repo = _import_envelope_repo()
    persist_repo = _import_macro_story_repo()
    ws_publisher = _import_ws_publisher()

    episodic = EpisodicMemoryService(embedding_service=embedding_service)
    poller = ReleasePoller()

    return MacroStoryTracker(
        poller=poller,
        episodic_memory_service=episodic,
        b6_hook=message_loop_prompts_before_b6,
        llm_router=llm_router,
        embedding_service=embedding_service,
        envelope_repo=envelope_repo,
        persist_repo=persist_repo,
        ws_publisher=ws_publisher,
    )


def _import_embedding_service():
    """Phase 58 EmbeddingService singleton (768-dim all-mpnet-base-v2)."""
    try:
        from core.embeddings import EmbeddingService  # type: ignore[import]
        return EmbeddingService()
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "core.embeddings.EmbeddingService not importable — Plan 87-14 "
            "deploy gate must wire Phase 58 EmbeddingService before the "
            "sibling service can run."
        ) from exc


def _import_llm_router():
    """Phase 43 LLM router. Falls back to RuntimeError at deploy time."""
    try:
        from core.runtime import llm_router  # type: ignore[import]
        return llm_router
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "core.runtime.llm_router not importable — Plan 87-14 deploy "
            "gate must wire the Phase 43 LLM router before the sibling "
            "service can run."
        ) from exc


def _import_envelope_repo():
    """Phase 70.5 envelope writer."""
    try:
        from core.runtime import envelope_repo  # type: ignore[import]
        return envelope_repo
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "core.runtime.envelope_repo not importable — Plan 87-14 "
            "deploy gate must wire the Phase 70.5 envelope writer."
        ) from exc


def _import_macro_story_repo():
    """VM101 macro_story Postgres DAL (lands at deploy time)."""
    try:
        from persist.macro_story_repo import MacroStoryRepo  # type: ignore[import]
        return MacroStoryRepo()
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "persist.macro_story_repo.MacroStoryRepo not importable — "
            "Plan 87-14 deploy gate must wire the VM101 macro_story DAL."
        ) from exc


def _import_ws_publisher():
    """VM100 WS topic publisher (macro.story.updated)."""
    try:
        from core.runtime import ws_publisher  # type: ignore[import]
        return ws_publisher
    except ImportError as exc:  # pragma: no cover — deploy-time wiring
        raise RuntimeError(
            "core.runtime.ws_publisher not importable — Plan 87-14 deploy "
            "gate must wire the WS publisher."
        ) from exc


def _record_last_run() -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(tz=timezone.utc).isoformat())


def _run_tick(tracker) -> None:
    """Execute one tick, write the heartbeat, log the stats. Never raise."""
    try:
        stats = tracker.run_once()
        _record_last_run()
        logger.info({"event": "macro_story_tracker_tick", **stats})
    except Exception as exc:  # noqa: BLE001
        logger.exception({"event": "macro_story_tracker_tick_failed",
                          "error": str(exc)})


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Fail-fast on required env BEFORE wiring expensive collaborators.
    _env_required("VM101_INTERNAL_BASE_URL")
    _env_required("QDRANT_URL")

    from apscheduler.schedulers.blocking import BlockingScheduler

    tracker = _build_tracker()
    sched = BlockingScheduler(timezone="UTC")

    sched.add_job(
        _run_tick,
        trigger="cron",
        minute=5,
        kwargs={"tracker": tracker},
        id="macro_story_tracker_hourly",
        max_instances=1,
        coalesce=True,
    )

    # Run an immediate first tick so the healthcheck has a valid heartbeat
    # before the hourly cron fires. Without this the sibling service flaps
    # unhealthy for ≤90 minutes on first boot.
    logger.info({"event": "macro_story_tracker_starting"})
    _run_tick(tracker)

    sched.start()


if __name__ == "__main__":  # pragma: no cover — exercised by the sibling service
    main()
