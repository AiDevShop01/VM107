"""Phase 92 Plan 05 — ContrarianAgent.

Identifies cases where a research document claims a contrarian view vs the
consensus on its linked indicator (e.g. 'Higher CPI did NOT hurt gold in
this episode'). Writes to MongoDB `research_intelligence_contrarian`.

impact_on_decision: HIGH (surfaces dissenting evidence; drives Plan 6
Contrarian Views card; informs Phase 89 macro_investigator).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.research import storage


_PROMPT_TEMPLATE = """\
You are evaluating whether the following research document claims a CONTRARIAN
view vs the consensus on its linked indicator(s).

A contrarian claim is a statement that contradicts the conventional wisdom or
the consensus narrative on a macro relationship. Examples:
- "Higher CPI did NOT correlate with gold appreciation in this episode."
- "Rate cuts paradoxically tightened financial conditions."
- "The dollar regime decoupled from yield differentials in 2022."

Title: {title}
Linked indicators: {indicators}

Text:
{body}

Respond with STRICT JSON only (no markdown, no preamble):
{{
  "contrarian_claim": "<the contrarian claim text, or empty string if none>",
  "evidence_chunks": ["<verbatim supporting sentence>", ...],
  "confidence": <float between 0.0 and 1.0>
}}
"""


@dataclass(frozen=True)
class ContrarianResult:
    doc_id: str
    indicator_id: str
    contrarian_claim: str
    evidence_chunks: list[str]
    confidence: float


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Tolerate small JSON wrap noise (code fences, leading prose)."""
    s = raw.strip()
    if s.startswith("```"):
        # Strip ```json ... ``` fences
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    # Trim to outermost braces
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    return json.loads(s)


class ContrarianAgent:
    """REQ-92-6 — surfaces contrarian claims vs indicator consensus."""

    def __init__(self, llm_caller: Any | None = None, min_confidence: float = 0.6) -> None:
        self._llm = llm_caller
        self._min_confidence = min_confidence

    def _call_llm(self, prompt: str) -> str:
        if self._llm is not None:
            return self._llm(prompt)
        from services import llm_client

        return llm_client.call_llm(prompt)

    def process(self, doc: Any) -> ContrarianResult | None:
        document_id = getattr(doc, "document_id", None) or doc["document_id"]
        body = getattr(doc, "body", None) or doc.get("body", "")
        title = getattr(doc, "title", None) or doc.get("title", "")
        indicators = getattr(doc, "indicators", None) or doc.get("indicators", [])
        if not indicators:
            return None
        primary_indicator = indicators[0]

        prompt = _PROMPT_TEMPLATE.format(
            title=title, indicators=indicators, body=body
        )
        raw = self._call_llm(prompt)

        try:
            parsed = _parse_llm_json(raw)
        except (ValueError, TypeError):
            return None

        claim = (parsed.get("contrarian_claim") or "").strip()
        evidence = [e for e in (parsed.get("evidence_chunks") or []) if e]
        confidence = float(parsed.get("confidence") or 0.0)

        if not claim:
            return None

        result = ContrarianResult(
            doc_id=document_id,
            indicator_id=primary_indicator,
            contrarian_claim=claim,
            evidence_chunks=evidence,
            confidence=confidence,
        )

        storage.write_contrarian(
            doc_id=result.doc_id,
            indicator_id=result.indicator_id,
            contrarian_claim=result.contrarian_claim,
            evidence_chunks=result.evidence_chunks,
            confidence=result.confidence,
        )
        return result
