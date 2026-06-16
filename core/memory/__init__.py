"""Phase 87 Wave 4a — Brain B6 EpisodicMemoryService package surface.

Re-exports the public contract types so callers can write::

    from VM107.core.memory import (
        EpisodicMemoryService,
        EpisodicQuery,
        EpisodicResult,
        MemoryRecord,
        CitationRef,
    )
"""
from VM107.core.memory.episodic_memory_service import (  # noqa: F401
    CitationRef,
    EpisodicMemoryService,
    EpisodicQuery,
    EpisodicResult,
    MemoryRecord,
)
from VM107.core.memory.qdrant_macro_episode_collection import (  # noqa: F401
    COLLECTION_NAME,
    ensure_macro_episode_collection,
)
