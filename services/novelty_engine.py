"""
Re-export shim for VM107/services/novelty_engine.py.

The canonical implementation lives at ``emitters.novelty_engine``.
This module re-exports all public symbols so that either import path works:

    from emitters.novelty_engine import NoveltyEngine, NoveltyDimensions
    from services.novelty_engine import NoveltyEngine, NoveltyDimensions  # also works

Per CONTEXT.md §2 key_links, Wave 2 emitters will import from the emitters
package directly.  This shim satisfies plan 66-02's files_modified spec
(VM107/services/novelty_engine.py) without duplicating implementation.
"""
from emitters.novelty_engine import (  # noqa: F401
    NoveltyDimensions,
    NoveltyEngine,
    NoveltyScore,
    CONFIG_PATH,
)

__all__ = ["NoveltyEngine", "NoveltyDimensions", "NoveltyScore", "CONFIG_PATH"]
