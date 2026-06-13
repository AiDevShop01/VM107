"""Phase 85 Plan 10/11 — production factory for BrainOrchestrator.

Builds the full GoalService dependency tree from environment-driven config
and returns a ready-to-use BrainOrchestrator. Called once at VM107 worker
startup (listener main()).

Env requirements (fail-fast on miss):
  REDIS_URL          — vm107-redis pubsub + queue
  MONGODB_URI        — vm107 Brain Mongo cluster
  VM107_BRAIN_DB     — Mongo database name (default: vm107_brain)
  VM107_TEMPLATES_DIR — task decomposition templates (default: /a0/config/templates)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"{key} env var is unset. Required for Phase 85 Brain orchestrator boot."
        )
    return val


def build_default_orchestrator() -> Any:
    """Construct a production BrainOrchestrator wired to MongoDB + Redis.

    Returns:
        A configured BrainOrchestrator instance ready for
        configure_default_orchestrator().

    Raises:
        RuntimeError: If REDIS_URL or MONGODB_URI is not set.
    """
    import pymongo
    import redis as redis_lib

    from core.decomposition.engine import DecompositionEngine
    from core.decomposition.templates import TemplateLoader
    from core.persistence.bulk_writer import TieredBulkWriter
    from core.persistence.mongo_cache import MongoCachedCollection
    from core.persistence.redis_queue import RedisPriorityQueue
    from core.scheduling.dag import DAGValidator
    from core.scheduling.goal_service import GoalService
    from core.scheduling.governance import GovernanceMatrix
    from core.scheduling.macro_release_goal import BrainOrchestrator

    redis_url = _required("REDIS_URL")
    mongo_uri = _required("MONGODB_URI")
    brain_db_name = os.environ.get("VM107_BRAIN_DB", "vm107_brain")
    templates_dir = Path(
        os.environ.get("VM107_TEMPLATES_DIR", "/a0/config/templates")
    )

    if not templates_dir.exists():
        raise RuntimeError(
            f"VM107_TEMPLATES_DIR does not exist: {templates_dir}. "
            f"Required for DecompositionEngine."
        )

    redis_client = redis_lib.from_url(redis_url)
    mongo_client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)

    # Fail-fast: verify Mongo is reachable at boot, not on first write.
    mongo_client.admin.command("ping")

    brain_db = mongo_client[brain_db_name]
    # GoalService and BrainOrchestrator both call bulk_writer.write_critical()
    # with `_id` set to either goal_id or task_id, so a single shared
    # collection works for both — IDs are namespaced (`goal_`/`task_` prefixes)
    # and won't collide. Two separate read caches still gain coherency from
    # the cache_prefix split.
    brain_state = brain_db["brain_state"]
    brain_state.create_index("goal_id")
    brain_state.create_index("task_id")

    goal_cache = MongoCachedCollection(
        brain_state,
        redis_client,
        cache_prefix="brain:goal",
        ttl=60,
    )
    task_cache = MongoCachedCollection(
        brain_state,
        redis_client,
        cache_prefix="brain:task",
        ttl=60,
    )
    bulk_writer = TieredBulkWriter(brain_state)

    dag_validator = DAGValidator()
    template_loader = TemplateLoader(templates_dir)
    decomposition_engine = DecompositionEngine(template_loader, dag_validator)
    governance = GovernanceMatrix()
    queue = RedisPriorityQueue(redis_client)

    goal_service = GoalService(
        goal_cache=goal_cache,
        task_cache=task_cache,
        bulk_writer=bulk_writer,
        decomposition_engine=decomposition_engine,
        governance=governance,
        dag_validator=dag_validator,
        queue=queue,
    )

    orchestrator = BrainOrchestrator(goal_service=goal_service)

    logger.info({
        "event": "phase85_brain_orchestrator_built",
        "mongo_db": brain_db_name,
        "templates_dir": str(templates_dir),
    })

    return orchestrator
