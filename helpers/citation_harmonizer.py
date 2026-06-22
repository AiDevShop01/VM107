"""Citation schema harmonizer — Phase 89.1 Plan 01 follow-up fix (2026-06-22).

Converts VM107 B1 CitationRef dicts (citation_id / source / snippet)
to the VM100-compatible Citation dict shape (ref_id / kind / label)
that _parse_ask_response() in VM100/backend/api/macro/ask.py expects.

Context:
  89.1-05 WAVE3-THRESHOLD-REPORT revealed that all 20 UAT requests were
  returning HTTP 500.  Stack trace:

    /app/api/macro/ask.py:137 in _parse_ask_response
    → citations = [Citation(**c) if isinstance(c, dict) else c for c in citations_raw]
    TypeError: unexpected keyword argument 'citation_id'

  VM107 was returning B1 CitationRef objects verbatim.  VM100's Citation
  Pydantic schema expects {ref_id, kind, label}.

Source → kind mapping:
  search_knowledge:*   → "research"   (Qdrant semantic search / FRED lookups)
  vm102.indicator_*    → "indicator"  (time-series indicators)
  vm102.structural_*   → "episode"    (structural break events)
  vm102.regime_*       → "episode"    (regime classification results)
  vm102.analogue_*     → "episode"    (analogue matching episodes)
  (anything else)      → "research"   (safe fallback — never drop a citation)

The VM100 Citation.kind field uses `kind: str` (not a Literal enum), so any
string value is accepted by Pydantic.  The new kind "research" is valid and
was added to the serializers.py docstring in the same fix batch.

Reference:
  .planning/phases/89.1-.../89.1-01-wave1-fence-block-citation-extraction-SUMMARY.md
  (Follow-up fix section, 2026-06-22)
"""
from __future__ import annotations

_MAX_LABEL_LEN = 120

# Source prefix → VM100 Citation.kind
_SOURCE_KIND_MAP: list[tuple[str, str]] = [
    ("vm102.indicator_", "indicator"),
    ("vm102.structural_", "episode"),
    ("vm102.regime_", "episode"),
    ("vm102.analogue_", "episode"),
    ("search_knowledge", "research"),
]


def _derive_kind(source: str) -> str:
    """Map a B1 citation source string to a VM100 Citation kind."""
    src_lower = source.lower()
    for prefix, kind in _SOURCE_KIND_MAP:
        if src_lower.startswith(prefix):
            return kind
    return "research"  # safe fallback


def _derive_label(source: str, snippet: str | None) -> str | None:
    """Derive a human-readable label from snippet (preferred) or source."""
    if snippet:
        return snippet[:_MAX_LABEL_LEN]
    # Fall back to the source string itself, stripped of the tool prefix
    # e.g. "search_knowledge: FRED 'U.S. CPI'" → "FRED 'U.S. CPI'"
    if ": " in source:
        label = source.split(": ", 1)[1]
    else:
        label = source
    return label[:_MAX_LABEL_LEN] if label else None


def _harmonize_one(c: dict) -> dict:
    """Harmonize a single citation dict.

    If the dict already uses ref_id/kind (already harmonized or came from
    the model's own envelope), pass it through unchanged.
    If it uses citation_id/source/snippet (B1 CitationRef shape), convert it.
    """
    # Already in VM100 shape — pass through (idempotent).
    if "ref_id" in c:
        return {
            "ref_id": c["ref_id"],
            "kind": c.get("kind", "research"),
            "label": c.get("label"),
        }

    # B1 CitationRef shape — convert.
    citation_id = c.get("citation_id", "")
    source = c.get("source", "")
    snippet = c.get("snippet")

    return {
        "ref_id": citation_id,
        "kind": _derive_kind(source),
        "label": _derive_label(source, snippet),
    }


def harmonize_citations(citations: list[dict]) -> list[dict]:
    """Convert a list of citation dicts to VM100-compatible shape.

    Handles both B1 CitationRef dicts and already-harmonized dicts (idempotent).
    Never drops citations — unknown sources fall back to kind='research'.

    Args:
        citations: List of citation dicts from agent0.get_data("citations") or
                   from a parsed fence envelope.  May be empty.

    Returns:
        List of dicts with keys: ref_id (str), kind (str), label (str | None).
        Each dict is a valid Citation(**c) constructor argument for VM100.
    """
    return [_harmonize_one(c) for c in citations]
