"""Backend factory for creating MemoryBackend instances from config.

D-04 / SC-2: ``create_qdrant_client`` is the SINGLE sanctioned Qdrant client
construction site in the runtime import graph. Every runtime caller
(``create_backend`` here, ``helpers/memory.py``, ``core/memory/episodic_memory_service.py``,
``tools/find_countries_by_profile_query.py``) routes through it; the two ops
scripts (migrate_faiss_to_qdrant, backfill_macro_episodes) are the only
sanctioned exceptions and live outside the agent import graph. This kills the
"which QdrantClient path is live?" fragility and carries the P1 timeout to every
caller. See ``tests/phase138/test_single_qdrant_factory.py`` (the exactly-one gate).
"""

import os
from typing import Any
from plugins._memory.backend.base import MemoryBackend
from plugins._memory.backend.faiss_backend import FaissBackend
from plugins._memory.backend.qdrant_backend import QdrantBackend


def create_qdrant_client(
    config: dict | None = None,
    *,
    probe: bool = False,
):
    """Single sanctioned Qdrant client construction site (D-04 / SC-2).

    Supports BOTH construction styles used across the runtime so every caller can
    route through one factory without changing its addressing scheme:
      * URL-style (episodic_memory_service, find_countries): ``config['qdrant_url']``
        + optional ``config['api_key']`` / ``config['check_compatibility']``.
      * host/port-style (create_backend, helpers/memory): ``config['qdrant_host']``
        (else ``QDRANT_HOST`` env) + ``config.get('qdrant_port', 6333)``.

    The P1 timeout (``A0_QDRANT_TIMEOUT`` default 5s) is applied to EVERY caller —
    this is the sync-blocking-in-async fix: a down Qdrant fast-fails within budget
    instead of hanging. Env-driven resilience bound, not a target/credential
    fallback (D-05/D-06).

    SYNC client + sync return (RESEARCH A1): two runtime callers use the client in
    SYNCHRONOUS methods (episodic ``query()``, find_countries ``run()``), so an
    ``AsyncQdrantClient`` cannot serve them without a cascading async refactor of
    their public methods. Keeping the sync client is the behavior-preserving path
    that still satisfies "exactly one factory" (SC-2). The async swap remains a
    future hardening step gated on the P1 recall benchmark.

    Args:
        config: construction config (see styles above). ``None`` → host/port from env.
        probe: when True (the ``create_backend`` / phase134 chaos path), run a
            bounded ``get_collections()`` liveness probe and report the ``qdrant``
            SourceHealthRegistry signal (available on success; unavailable + re-raise
            on failure). When False (episodic/find_countries/memory lazy paths),
            construct-and-return, preserving each caller's existing failure semantics.

    Returns:
        A configured ``qdrant_client.QdrantClient`` (sync).
    """
    from qdrant_client import QdrantClient

    config = config or {}

    # timeout bounds every request so a down Qdrant fast-fails within budget
    # instead of hanging (P1 / SC-1). Env-driven resilience default (D-05/D-06).
    timeout = int(os.getenv("A0_QDRANT_TIMEOUT", "5"))

    qdrant_url = config.get("qdrant_url")
    if qdrant_url:
        kwargs: dict[str, Any] = {"url": qdrant_url, "timeout": timeout}
        if config.get("api_key"):
            kwargs["api_key"] = config["api_key"]
        if "check_compatibility" in config:
            kwargs["check_compatibility"] = config["check_compatibility"]
    else:
        qdrant_host = config.get("qdrant_host") or os.environ["QDRANT_HOST"]
        qdrant_port = config.get("qdrant_port", 6333)
        kwargs = {"host": qdrant_host, "port": qdrant_port, "timeout": timeout}

    # The ONE raw construction line in the runtime import graph (SC-2).
    client = QdrantClient(**kwargs)

    if not probe:
        return client

    from emitters.source_health_registry import SourceHealthRegistry

    # Bounded liveness probe. QdrantClient construction is lazy — against a down
    # host the version check only *warns*, so a broken backend would be handed back
    # and fail (silently swallowed) on first real use with NO degrade signal. Probe
    # an actual op here so a down Qdrant fast-fails WITHIN the client timeout and
    # emits its `qdrant` degrade signal (SC-2 observability), instead of deferring an
    # unobserved failure. Healthy path cost: one bounded round-trip (D-07 fail-fast).
    try:
        client.get_collections()
    except Exception as exc:
        SourceHealthRegistry.get_shared_instance().report(
            "qdrant", available=False, failure_reason=str(exc)
        )
        raise
    SourceHealthRegistry.get_shared_instance().report("qdrant", available=True)
    return client


def create_backend(
    config: dict,
    embedding_service: Any | None = None,
) -> MemoryBackend:
    """Create MemoryBackend instance based on config.

    Args:
        config: Configuration dict with memory_backend key
        embedding_service: EmbeddingService instance (required for Qdrant)

    Returns:
        MemoryBackend instance (FaissBackend or QdrantBackend)

    Raises:
        ValueError: If memory_backend value is invalid
        ValueError: If Qdrant selected but embedding_service not provided

    Example config:
        {
            "memory_backend": "faiss",  # or "qdrant"
            "qdrant_host": "192.168.1.151",
            "qdrant_port": 6333,
        }
    """
    backend_type = config.get("memory_backend", "faiss")

    if backend_type == "faiss":
        # FaissBackend wraps existing MyFaiss initialization
        # Agent parameter will be set by Memory.get()
        return FaissBackend(agent=None)

    elif backend_type == "qdrant":
        if embedding_service is None:
            raise ValueError(
                "embedding_service is required for Qdrant backend"
            )

        # Delegate to the single sanctioned construction site (D-04 / SC-2):
        # create_qdrant_client carries the P1 timeout + bounded liveness probe +
        # SourceHealthRegistry degrade wiring (probe=True = the phase134 chaos
        # gate path). No raw client construction here — factory.py holds
        # exactly one ctor, inside create_qdrant_client.
        client = create_qdrant_client(config, probe=True)

        return QdrantBackend(
            client=client,
            embedding_service=embedding_service,
            collection_name="agent_memory",
        )

    else:
        raise ValueError(
            f"Unknown memory_backend: {backend_type}. "
            f"Valid options: 'faiss', 'qdrant'"
        )
