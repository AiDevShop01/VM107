"""Plan 87-14 deploy-gate envelope-writer bridge (Phase 70.5, additive).

The macro_story_tracker runner imports ``from core.runtime import envelope_repo``
and the agent calls
``envelope_repo.persist(analysis_kind=..., payload=...) -> envelope_id``
(see ``agents/macro_story_tracker/agent.py`` — the CREATE path), then stores the
returned id as ``macro_story.generated_by_envelope_id`` for provenance.

This bridges that one-method contract to the canonical envelope writer
``core.agents.envelope_writer`` (``build_envelope`` + ``write_envelope``), which
persists an ``AgentEnvelope`` to the MongoDB ``agent_envelopes`` collection under
the Phase 43.2 convention (``_id == envelope_id == str(uuid4)``). No existing
module is modified — this only exposes the expected name/method, mirroring the
``core.runtime.llm_router`` bridge.

Reachability note (Plan 87-14): ``persist`` runs only on a CREATE decision, i.e.
AFTER ``llm_router.complete`` returns — which needs ``LLM_MODEL`` / ``LLM_API_KEY``
(still unwired for the macro_* container profile). So the tracker boots past this
guard, but this write path is not exercised until those creds land. Verified:
importable, and its collaborators (pymongo, CapabilityRegistry, build_envelope)
are present in the runner venv.

All heavy imports/connections are deferred to call time so importing this module
(deploy-gate guard, pytest collection) is dependency-free.
"""
from __future__ import annotations

import logging
import os
import uuid

log = logging.getLogger(__name__)

# WR-08: pymongo clients are meant to be long-lived and reused. persist() runs per
# macro_story_tracker CREATE tick; constructing (and never closing) a fresh MongoClient
# each call leaked a connection pool per tick. Cache one client per URI at module scope.
_MONGO_CLIENTS: dict = {}


def _get_client(mongo_url: str):
    """Return a cached long-lived MongoClient for the URI, creating it if absent.

    serverSelectionTimeoutMS bounds the (lazy) first op so a down Mongo fast-fails
    instead of hanging the tracker tick (SC-1).
    """
    client = _MONGO_CLIENTS.get(mongo_url)
    if client is None:
        import pymongo

        client = pymongo.MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=int(os.getenv("A0_MONGO_TIMEOUT_MS", "5000")),
        )
        _MONGO_CLIENTS[mongo_url] = client
    return client


def persist(*, analysis_kind: str, payload: dict) -> str:
    """Persist an analysis envelope and return its envelope_id.

    Args:
        analysis_kind: e.g. "macro_story_create" — recorded on the envelope
            input so the provenance chain identifies why it was written.
        payload: The analysis payload (headline + pattern for macro stories).

    Returns:
        The envelope_id (str uuid) — also the MongoDB _id.

    Raises:
        Propagates on Mongo/registry failure. The caller (agent CREATE path)
        treats a failed persist as a failed tick; the runner's tick wrapper
        logs it without crashing the loop.
    """
    # Deferred imports — see module docstring.
    from pathlib import Path

    from core.agents.envelope_writer import build_envelope, write_envelope
    from core.registry.capability_registry import CapabilityRegistry
    from emitters.source_health_registry import SourceHealthRegistry

    # build_envelope stamps registry provenance via CapabilityRegistry.get();
    # ensure the registry is initialized in this (runner) process first.
    try:
        CapabilityRegistry.get()
    except RuntimeError:
        registry_root = os.environ.get("CAPABILITY_REGISTRY_ROOT")
        if not registry_root:
            raise
        CapabilityRegistry.initialize(Path(registry_root))

    mongo_url = os.environ.get("BELIEF_STORE_MONGO_URL")
    if not mongo_url:
        raise RuntimeError(
            "BELIEF_STORE_MONGO_URL required for envelope_repo.persist — "
            "env-driven, no default"
        )
    # WR-08: reuse a cached long-lived client (canonical shape:
    # core/scheduling/orchestrator_factory.py:69, minus the boot ping).
    db = _get_client(mongo_url).get_default_database()

    envelope = build_envelope(
        task_id=f"macro-story-{uuid.uuid4()}",
        parent_task_id=None,
        agent_id="macro_story_tracker",
        input_payload={"analysis_kind": analysis_kind},
        output_payload=payload or {},
        telemetry={},
        status="success",
    )
    # Guard the first Mongo op (write_envelope) matching this module's
    # re-raise idiom (D-07): report health, then propagate as before.
    try:
        envelope_id = write_envelope(db, envelope)
    except Exception as exc:
        SourceHealthRegistry.get_shared_instance().report(
            "mongo", available=False, failure_reason=type(exc).__name__
        )
        raise
    SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
    return envelope_id
