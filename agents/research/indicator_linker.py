"""Phase 92 Plan 03 — Hybrid indicator linker (synonym table + LLM fallback).

Per 92-RESEARCH.md Pattern 4. Stage 1 is a case-insensitive substring search
against ``VM107/data/indicator_synonyms.yaml``. Stage 2 invokes
``_llm_classify_fallback`` ONLY when Stage 1 returned ∅, applies a 0.70
confidence threshold, and tags accepted hits with ``via='llm'``.

Public API:

    link_indicators(doc_text: str, doc_title: str)
        -> tuple[list[dict], str]

Returns (hits, linker_stage) where:
    hits = [{"indicator_id": str, "confidence": float, "via": "synonym"|"llm"}]
    linker_stage ∈ {"synonym", "llm", "none"}

Catalog source:
- Production: ``VM100_INDICATOR_CATALOG_URL`` env var (no fallback). The
  cross-VM read happens lazily on first use and is cached in-process for
  ``_CATALOG_TTL_SECONDS`` (default 3600s).
- Tests: ``PHASE92_INDICATOR_CATALOG_FILE`` env var. When set, the linker
  reads from the local YAML file instead of hitting VM100. The conftest
  fixture writes the locked 64-ID Phase 83 catalog there.

The catalog is consulted only to (a) reject synonym entries that reference
unknown FRED IDs (early integrity check) and (b) seed the LLM fallback
``candidate_indicators`` list (Pattern 4 lines 339-367 — the LLM picks from
the catalog, never invents IDs).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import yaml


# ── Configuration ──────────────────────────────────────────────────────
# Stage 2 LLM-fallback confidence threshold per plan must_haves block.
_LLM_CONFIDENCE_THRESHOLD: float = 0.70

# Catalog cache TTL (1h per spec)
_CATALOG_TTL_SECONDS: int = 3600

# Synonym table path — frozen at module import time
_VM107_ROOT = Path(__file__).resolve().parents[2]
_SYNONYM_TABLE_PATH = _VM107_ROOT / "data" / "indicator_synonyms.yaml"

# Lazy/cached state
_synonym_table_cache: list[tuple[str, list[str]]] | None = None
_catalog_cache: tuple[float, set[str]] | None = None  # (loaded_at_epoch, ids)


# ── Synonym table loader (Stage 1) ─────────────────────────────────────
def _load_synonym_table() -> list[tuple[str, list[str]]]:
    """Load + cache synonym_table as a list of (synonym_phrase, [indicator_ids]).

    Each entry: ('core cpi', ['CPILFESL']). Phrases are pre-lowered for
    case-insensitive matching.

    Schema (per indicator_synonyms.yaml):
        <concept_key>:
          match:
            "<phrase>": [<FRED_ID>, ...]
            ...

    The per-phrase mapping lets different phrasings within the same concept
    point at different indicators (e.g. 'core cpi' → [CPILFESL] vs
    'pce inflation' → [PCEPI]), which is what holds Stage-1 precision ≥0.95
    on the 30-doc golden set.
    """
    global _synonym_table_cache
    if _synonym_table_cache is not None:
        return _synonym_table_cache

    raw = yaml.safe_load(_SYNONYM_TABLE_PATH.read_text())
    out: list[tuple[str, list[str]]] = []
    for _concept_key, body in raw.items():
        match_block = body.get("match", {}) if isinstance(body, dict) else {}
        for phrase, indicator_ids in match_block.items():
            out.append((phrase.lower(), list(indicator_ids)))
    _synonym_table_cache = out
    return out


# ── Catalog loader (cross-VM or file path) ─────────────────────────────
def _load_indicator_catalog() -> set[str]:
    """Return the Phase 83 EconomicIndicator ID set. Cached for 1h.

    Test path: PHASE92_INDICATOR_CATALOG_FILE = /path/to/yaml/with/indicators
    Prod path: VM100_INDICATOR_CATALOG_URL    = http://vm100:.../catalog

    No fallback defaults; raises if neither env var is set.
    """
    global _catalog_cache
    now = time.time()
    if _catalog_cache is not None and (now - _catalog_cache[0]) < _CATALOG_TTL_SECONDS:
        return _catalog_cache[1]

    test_file = os.environ.get("PHASE92_INDICATOR_CATALOG_FILE")
    prod_url = os.environ.get("VM100_INDICATOR_CATALOG_URL")
    if test_file:
        data = yaml.safe_load(Path(test_file).read_text())
    elif prod_url:
        import httpx  # noqa: PLC0415 — local import; httpx is heavyweight

        resp = httpx.get(prod_url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    else:
        raise RuntimeError(
            "indicator_linker: catalog source missing — set either "
            "PHASE92_INDICATOR_CATALOG_FILE (tests) or "
            "VM100_INDICATOR_CATALOG_URL (production)"
        )

    if isinstance(data, dict) and "indicators" in data:
        items = data["indicators"]
    else:
        items = data

    ids = {e["id"] if isinstance(e, dict) else str(e) for e in items}
    _catalog_cache = (now, ids)
    return ids


# ── Stage 1: synonym substring match ───────────────────────────────────
def _stage1_synonym_match(doc_text: str, doc_title: str) -> list[dict[str, Any]]:
    """Case-insensitive substring search of synonym table against title + text.

    Aggregates duplicates: if multiple synonyms map to the same indicator_id,
    only one hit is returned (confidence=1.0, via='synonym').
    """
    blob = f"{doc_title or ''}\n{doc_text or ''}".lower()
    seen: dict[str, dict[str, Any]] = {}
    for phrase, indicator_ids in _load_synonym_table():
        if phrase in blob:
            for iid in indicator_ids:
                if iid not in seen:
                    seen[iid] = {
                        "indicator_id": iid,
                        "confidence": 1.0,
                        "via": "synonym",
                    }
    return list(seen.values())


# ── Stage 2: LLM fallback ──────────────────────────────────────────────
def _llm_classify_fallback(
    doc_text: str,
    doc_title: str,
    candidate_indicators: list[str],
) -> list[dict[str, Any]]:
    """Production LLM fallback path.

    Builds a Phase 70.5 ToolResultEnvelope-shaped prompt asking the LLM
    "which of these FRED indicators does the document discuss?", parses
    the response as a list of {indicator_id, confidence} entries.

    For Plan-03 first cut this uses ``services/llm_client.call_llm()``
    which is the same synchronous LiteLLM wrapper Phase 86.7 / 90 use.

    Returns: list of {"indicator_id": str, "confidence": float} entries.

    Tests REPLACE this function via monkeypatch.setattr — so the production
    implementation here is best-effort and resilient: failures return [].
    """
    try:
        from services.llm_client import call_llm  # noqa: PLC0415
    except Exception:
        return []

    if not candidate_indicators:
        return []

    prompt = _build_llm_prompt(doc_text, doc_title, candidate_indicators)
    try:
        raw = call_llm(prompt)
    except Exception:
        return []

    return _parse_llm_response(raw, candidate_indicators)


def _build_llm_prompt(doc_text: str, doc_title: str, candidates: list[str]) -> str:
    head = doc_text[:2000]  # bound prompt size
    return (
        "You are a macro research classifier. Given the document title and "
        "an excerpt, identify which FRED EconomicIndicator IDs from the "
        "candidate list the document SUBSTANTIVELY discusses (not merely "
        "mentions in passing).\n\n"
        f"Title: {doc_title}\n\n"
        f"Excerpt:\n{head}\n\n"
        f"Candidate FRED IDs (choose from these, do NOT invent new IDs):\n"
        f"{', '.join(sorted(candidates))}\n\n"
        "Respond with ONE line per indicator you identify, in the form:\n"
        "  <FRED_ID>\\t<confidence_0_to_1>\n"
        "If the document does not substantively discuss any of these "
        "indicators, respond with the single token NONE.\n"
    )


def _parse_llm_response(
    raw: str, candidate_indicators: list[str]
) -> list[dict[str, Any]]:
    """Parse the FRED_ID<TAB>confidence line format from the LLM."""
    candidates = set(candidate_indicators)
    out: list[dict[str, Any]] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.upper() == "NONE":
            continue
        parts = line.replace(",", "\t").split("\t")
        if len(parts) < 2:
            parts = line.split()
        if len(parts) < 2:
            continue
        iid = parts[0].strip()
        if iid not in candidates:
            continue
        try:
            conf = float(parts[1].strip())
        except ValueError:
            continue
        out.append({"indicator_id": iid, "confidence": conf})
    return out


# ── Public API ─────────────────────────────────────────────────────────
def link_indicators(
    doc_text: str, doc_title: str
) -> tuple[list[dict[str, Any]], str]:
    """Hybrid Stage 1 (synonym) + Stage 2 (LLM fallback) indicator linker.

    Returns (hits, linker_stage):
      hits         : list of {indicator_id, confidence, via}
      linker_stage : 'synonym' if Stage 1 found ≥1 hit
                     'llm'     if Stage 1 returned ∅ and Stage 2 found ≥1 accepted hit
                     'none'    if neither stage produced a hit (caller soft-rejects)
    """
    stage1 = _stage1_synonym_match(doc_text=doc_text, doc_title=doc_title)
    if stage1:
        return stage1, "synonym"

    # Stage 2 — LLM fallback, gated at _LLM_CONFIDENCE_THRESHOLD.
    catalog_ids = sorted(_load_indicator_catalog())
    raw_hits = _llm_classify_fallback(
        doc_text=doc_text,
        doc_title=doc_title,
        candidate_indicators=catalog_ids,
    )
    accepted: list[dict[str, Any]] = []
    for h in raw_hits:
        if h.get("confidence", 0.0) >= _LLM_CONFIDENCE_THRESHOLD:
            accepted.append(
                {
                    "indicator_id": h["indicator_id"],
                    "confidence": float(h["confidence"]),
                    "via": "llm",
                }
            )

    if accepted:
        return accepted, "llm"
    return [], "none"


__all__ = [
    "link_indicators",
    "_stage1_synonym_match",
    "_llm_classify_fallback",
]
