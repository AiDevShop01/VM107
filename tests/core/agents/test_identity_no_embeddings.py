"""Phase 48 Plan 48-05 Task 5.1 — identity_scorer has NO embeddings.

REQ-48-D10. CONTEXT § Decision 10 + § Anti-Patterns:
  "Embedding/semantic similarity for identity drift" is explicitly REJECTED.
  Phase 47.6 lock: "no probabilistic discovery in cognition paths."

AST inspection rejects any import from the banned-embedding-library set.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_BANNED_IMPORT_PREFIXES = (
    "sentence_transformers",
    "openai",
    "openai.embeddings",
    "embeddings",
    "faiss",
    "sklearn.metrics.pairwise",
    "sklearn.metrics",
    "numpy.linalg",  # cosine via norm
    "scipy.spatial",
    "tiktoken",
)

_IDENTITY_SCORER_PATH = pathlib.Path(
    "/Volumes/ HardDrive/FinGPT/VM107/core/agents/refinement_orchestrator/identity_scorer.py"
)


def test_identity_scorer_imports_no_embedding_library():
    """ast.walk identity_scorer.py — fail if any banned import appears."""
    assert _IDENTITY_SCORER_PATH.is_file(), _IDENTITY_SCORER_PATH
    tree = ast.parse(_IDENTITY_SCORER_PATH.read_text())

    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for banned in _BANNED_IMPORT_PREFIXES:
                    if alias.name == banned or alias.name.startswith(banned + "."):
                        offenders.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for banned in _BANNED_IMPORT_PREFIXES:
                if mod == banned or mod.startswith(banned + "."):
                    offenders.append((mod, node.lineno))

    assert not offenders, (
        "identity_scorer.py must NEVER import embedding libraries; "
        f"found: {offenders}"
    )


def test_identity_scorer_uses_no_vector_similarity_keywords():
    """Defense-in-depth: source-text search for vector-similarity terms.

    The structured-diff approach uses Pydantic model_fields + json_schema_extra
    -- never cosine_similarity / dot products / embedding vectors / etc.
    """
    src = _IDENTITY_SCORER_PATH.read_text()
    banned_substrings = (
        "cosine_similarity",
        "cosine_distance",
        "encode(",
        "embedding",
        "Embedding",
        ".vectors",
        "from_pretrained",
    )
    offenders = [s for s in banned_substrings if s in src]
    assert not offenders, (
        "identity_scorer.py must use structured-diff over Pydantic fields, "
        f"not vector similarity; banned tokens found: {offenders}"
    )


def test_identity_scorer_reads_field_metadata_via_pydantic():
    """The implementation must use Pydantic model_fields introspection.

    This is a positive guard -- if the implementation walks the spec via
    model_fields, the AST will contain "model_fields" or "json_schema_extra".
    """
    src = _IDENTITY_SCORER_PATH.read_text()
    # Either model_fields introspection OR direct json_schema_extra access is acceptable.
    assert "model_fields" in src, (
        "identity_scorer.py must walk StrategySpec.model_fields for "
        "structured field-level diff"
    )
    assert "json_schema_extra" in src or "mutability" in src, (
        "identity_scorer.py must consult FieldMutability metadata via "
        "json_schema_extra"
    )
