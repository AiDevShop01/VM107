"""
VM107 services package — shared service modules for all VM107 emitters.

The canonical novelty engine lives at ``emitters.novelty_engine``.
This package re-exports it for forward-compat with the import path
documented in CONTEXT.md §2 key_links:

    from VM107.services.novelty_engine import NoveltyEngine

Note: In tests, the VM107 root is on sys.path, so the import path is simply:
    from emitters.novelty_engine import NoveltyEngine  (preferred)
    from services.novelty_engine import NoveltyEngine  (also works)
"""
