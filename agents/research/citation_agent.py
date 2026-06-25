"""Phase 92 Plan 05 — CitationAgent.

Extracts cited references from research document text. Uses a deterministic
DOI regex for the primary path; an LLM fallback handles non-DOI references
when present (lazy, only when zero DOIs were extracted).

Writes to MongoDB `research_intelligence_citations`.

impact_on_decision: MEDIUM (drives Plan 6 References card but doesn't gate
investigative decisions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agents.research import storage


# Canonical CrossRef DOI pattern. Per https://www.crossref.org/blog/dois-and-matching-regular-expressions/
# we accept the broad shape; downstream consumers (re-)validate.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[\w\.\-_;()/:]+", re.IGNORECASE)


@dataclass(frozen=True)
class CitationResult:
    doc_id: str
    citations: list[dict[str, Any]]


def _strip_trailing_punct(doi: str) -> str:
    return doi.rstrip(".,;:)]\"'")


def _extract_dois(text: str) -> list[str]:
    """Deterministic DOI extraction. Dedup + strip trailing punctuation."""
    seen: list[str] = []
    for match in _DOI_RE.finditer(text or ""):
        doi = _strip_trailing_punct(match.group(0))
        if doi not in seen:
            seen.append(doi)
    return seen


class CitationAgent:
    """REQ-92-6 — extracts DOI / academic citations from a ResearchDocument."""

    def __init__(self, llm_caller: Any | None = None) -> None:
        self._llm = llm_caller

    def process(self, doc: Any) -> CitationResult:
        document_id = getattr(doc, "document_id", None) or doc["document_id"]
        body = getattr(doc, "body", None) or doc.get("body", "")
        title = getattr(doc, "title", None) or doc.get("title", "")
        indicators = getattr(doc, "indicators", None) or doc.get("indicators", [])
        primary_indicator = indicators[0] if indicators else None

        full_text = f"{title}\n{body}"
        dois = _extract_dois(full_text)

        citations: list[dict[str, Any]] = [
            {"doi": doi, "title": None, "year": None, "via": "doi_regex"}
            for doi in dois
        ]

        # LLM fallback is OPT-IN — only fires when no DOIs are detected AND a
        # caller-provided llm_caller is configured. Pure-deterministic by
        # default keeps citation extraction cheap + reproducible.
        if not citations and self._llm is not None:
            try:
                hits = self._llm(
                    "Extract any non-DOI academic citations (authors, year, title) "
                    f"from the following text. Return one per line.\n\n{full_text}"
                )
                for ln in (hits or "").splitlines():
                    ln = ln.strip(" -")
                    if ln:
                        citations.append({"doi": None, "title": ln, "year": None, "via": "llm"})
            except Exception:
                # Citation extraction failure must NOT break the pipeline.
                pass

        result = CitationResult(doc_id=document_id, citations=citations)

        storage.write_citation(
            doc_id=result.doc_id,
            indicator_id=primary_indicator,
            citations=result.citations,
        )

        return result
