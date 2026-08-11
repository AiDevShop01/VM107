"""Phase 138 (P6 / F1 — D-04) — the "exactly one QdrantClient factory" gate.

Walk-tree assertion copied in shape from ``tests/lint/test_no_direct_llm_calls.py``
(rglob the python tree, skip ``__pycache__`` + comment lines, assert a forbidden
pattern is confined to an allowlist). Here the "allowlist" is a single canonical
construction site: ``plugins/_memory/backend/factory.py``.

STATE AT AUTHORING (Wave 0): this test is DELIBERATELY RED. RESEARCH §2 enumerates
the runtime ``(Async)?QdrantClient(`` construction sites that exist BEFORE the Wave B
dedup:
  #1 plugins/_memory/backend/factory.py      (the canonical home — the ONLY survivor)
  #2 plugins/_memory/helpers/memory.py
  #3 core/memory/episodic_memory_service.py
  #4 tools/find_countries_by_profile_query.py

Wave B routes #2/#3/#4 through the factory; when exactly one site remains this test
flips GREEN. It is the SC-2 gate for that wave — the pre-state it documents now is
the contract the dedup must satisfy.

SCOPE BOUNDARY (RESEARCH §2): ``tests/`` and ``scripts/`` are EXCLUDED from the walk.
  * ``tests/`` — fixtures legitimately build read-only clients (e.g. this phase's
    ``conftest.qdrant_test_client``); they are not part of the agent import graph.
  * ``scripts/`` — the two ops-tooling sites, scripts/migrate_faiss_to_qdrant.py:65
    and scripts/backfill_macro_episodes.py:195 (RESEARCH §2 sites #5/#6), are
    one-shot migration/backfill tools OUTSIDE the agent runtime import graph. They
    would falsely inflate the count; excluding them keeps the gate on runtime code.
"""
from __future__ import annotations

import re
from pathlib import Path

# tests/phase138/ -> two levels up == VM107 root (== /a0 in-container).
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent

# The single sanctioned construction site after the Wave B dedup (D-04).
_CANONICAL_SITE = "plugins/_memory/backend/factory.py"

# Match `QdrantClient(` and `AsyncQdrantClient(` at a word boundary (the async swap
# is a Wave-B fallback option — RESEARCH A1 — so both spellings count as a site).
_QDRANT_CTOR = re.compile(r"\b(Async)?QdrantClient\s*\(")


def _walk_python_files(root: Path):
    """Yield every runtime .py file, skipping __pycache__ and the tests/scripts trees.

    Mirrors ``tests/lint/test_no_direct_llm_calls.py``'s walker; the tests+scripts
    exclusion is the RESEARCH §2 scope boundary documented in the module docstring.
    """
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        # EXCLUDE tests/ and scripts/ (ops tooling + fixtures) — RESEARCH §2 boundary.
        if "tests" in path.parts or "scripts" in path.parts:
            continue
        yield path


def _qdrant_construction_sites():
    """Return [(relpath, lineno)] of every non-comment (Async)?QdrantClient( site."""
    hits: list[tuple[str, int]] = []
    for path in _walk_python_files(_VM107_ROOT):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if _QDRANT_CTOR.search(line):
                hits.append((path.relative_to(_VM107_ROOT).as_posix(), lineno))
    return hits


def test_exactly_one_qdrant_client_construction():
    """Exactly one runtime QdrantClient construction site — plugins/_memory/backend/factory.py.

    RED at Wave 0 (multiple sites); the SC-2 gate that turns GREEN only when Wave B
    unifies the factory. The failure message lists every site so the dedup is bisectable.
    """
    hits = _qdrant_construction_sites()
    site_files = sorted({rel for rel, _ln in hits})
    assert site_files == [_CANONICAL_SITE], (
        "Expected exactly one runtime QdrantClient construction site "
        f"({_CANONICAL_SITE!r}); found {len(site_files)} distinct file(s):\n"
        + "\n".join(f"  {rel}:{ln}" for rel, ln in hits)
        + "\n(This test is EXPECTED RED at Wave 0 — it is the Wave B / SC-2 dedup gate.)"
    )
