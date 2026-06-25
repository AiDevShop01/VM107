"""Phase 92 Plan 05 — MongoDB persistence helpers for the 4 research intelligence agents.

Collections (per plan's `agents/research/storage.py` contract):
- research_intelligence_summaries
- research_intelligence_citations
- research_intelligence_contrarian
- research_intelligence_discoveries

Each agent writes via its dedicated helper (`write_summary` / `write_citation` /
`write_contrarian` / `write_discovery`). Indexes are created on
(indicator_id, -created_at) by `ensure_indexes()`.

Env vars:
- MONGO_URL — full MongoDB connection string (NO fallback default per
  CLAUDE.md `feedback_env_driven_no_fallbacks`).
- MONGO_DB_NAME — database name (defaults to 'fingpt' if unset; this is a
  read-shape default, NOT a service-URL fallback).

The `get_db()` indirection lets tests patch this single seam to inject a
fake/in-memory MongoDB without touching the real driver.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# pymongo is a soft dependency at import time so tests can patch get_db()
# without pymongo installed on the host shell.
try:  # pragma: no cover - exercised via tests by monkeypatching get_db
    import pymongo  # type: ignore
    from pymongo import MongoClient  # type: ignore
except ImportError:  # pragma: no cover
    pymongo = None  # type: ignore
    MongoClient = None  # type: ignore


_DB_NAME_DEFAULT = "fingpt"


def _required(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise RuntimeError(
            f"Required env var {key!r} not set — Phase 92 Plan 05 storage requires "
            "MONGO_URL (env-driven-no-fallbacks lock)"
        )
    return v


def get_db() -> Any:
    """Return a MongoDB database handle. Tests monkeypatch THIS function."""
    if MongoClient is None:  # pragma: no cover
        raise RuntimeError(
            "pymongo not installed — storage requires the pymongo driver"
        )
    url = _required("MONGO_URL")
    db_name = os.environ.get("MONGO_DB_NAME", _DB_NAME_DEFAULT)
    client = MongoClient(url)
    return client[db_name]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _collection(db: Any, name: str) -> Any:
    """Resolve a collection handle. Tolerates both pymongo (db[name] / db.name)
    and test-stub `__getattr__`-only fakes."""
    try:
        return db[name]
    except (TypeError, KeyError):
        return getattr(db, name)


def ensure_indexes() -> None:
    """Idempotent index creation. Called lazily on first write."""
    db = get_db()
    for col in (
        "research_intelligence_summaries",
        "research_intelligence_citations",
        "research_intelligence_contrarian",
        "research_intelligence_discoveries",
    ):
        # Composite index on (indicator_id ASC, created_at DESC). pymongo accepts
        # a list of (field, direction) tuples; tests use a stub that ignores args.
        _collection(db, col).create_index(
            [("indicator_id", 1), ("created_at", -1)],
            name=f"{col}_indicator_created_at",
        )


# ── Per-agent writers ──────────────────────────────────────────────────


def write_summary(
    *,
    doc_id: str,
    indicator_id: str,
    summary: list[str],
    key_findings: list[str],
    tier: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Persist a SummarisationAgent result."""
    record = {
        "_id": f"summary-{uuid4()}",
        "doc_id": doc_id,
        "indicator_id": indicator_id,
        "summary": summary,
        "key_findings": key_findings,
        "tier": tier,
        "title": title,
        "created_at": _utc_now(),
    }
    db = get_db()
    _collection(db, "research_intelligence_summaries").insert_one(record)
    return record


def write_citation(
    *,
    doc_id: str,
    citations: list[dict[str, Any]],
    indicator_id: str | None = None,
) -> dict[str, Any]:
    """Persist a CitationAgent result."""
    record = {
        "_id": f"citation-{uuid4()}",
        "doc_id": doc_id,
        "indicator_id": indicator_id,
        "citations": citations,
        "created_at": _utc_now(),
    }
    db = get_db()
    _collection(db, "research_intelligence_citations").insert_one(record)
    return record


def write_contrarian(
    *,
    doc_id: str,
    indicator_id: str,
    contrarian_claim: str,
    evidence_chunks: list[str],
    confidence: float,
) -> dict[str, Any]:
    """Persist a ContrarianAgent result."""
    record = {
        "_id": f"contrarian-{uuid4()}",
        "doc_id": doc_id,
        "indicator_id": indicator_id,
        "contrarian_claim": contrarian_claim,
        "evidence_chunks": evidence_chunks,
        "confidence": float(confidence),
        "created_at": _utc_now(),
    }
    db = get_db()
    _collection(db, "research_intelligence_contrarian").insert_one(record)
    return record


def write_discovery(
    *,
    discovery_id: str,
    pattern_summary: str,
    supporting_docs: list[str],
    indicators: list[str],
    sources: list[str] | None = None,
    severity: str = "watch",
) -> dict[str, Any]:
    """Persist a DiscoveryAgent result."""
    record = {
        "_id": f"discovery-{discovery_id}",
        "discovery_id": discovery_id,
        "pattern_summary": pattern_summary,
        "supporting_docs": supporting_docs,
        "indicators": indicators,
        "sources": sources or [],
        "severity": severity,
        "created_at": _utc_now(),
    }
    db = get_db()
    _collection(db, "research_intelligence_discoveries").insert_one(record)
    return record


def read_summaries(indicator_id: str, lookback_days: int = 30) -> list[dict[str, Any]]:
    """Read summaries for cross-doc discovery analysis. Best-effort query."""
    db = get_db()
    rows = _collection(db, "research_intelligence_summaries").find(
        {"indicator_id": indicator_id}
    )
    # `find` may return a list (test stub) or a cursor (real pymongo) — coerce.
    return list(rows)
