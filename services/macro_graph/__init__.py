"""Phase 87 Wave 1 — Macro graph seed loader + correlation augmenter.

Public surface:
    AffectsEdge, DrivesEdge      — frozen dataclasses for the two edge types
    CorrelationAugmenter         — best-effort VM102 correlation augmentation
    MacroGraphLoader, LoadReport — idempotent Neo4j MERGE loader

Used by the standalone script `scripts/load_macro_graph_seed.py` and by Wave 2+
tests against testcontainers Neo4j.
"""
from .correlation_augmentation import (
    AffectsEdge,
    CorrelationAugmenter,
    DrivesEdge,
)
from .loader import LoadReport, MacroGraphLoader

__all__ = [
    "AffectsEdge",
    "CorrelationAugmenter",
    "DrivesEdge",
    "LoadReport",
    "MacroGraphLoader",
]
