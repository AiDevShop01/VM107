"""Phase 92 Plan 05 — SummarisationAgent.

Consumes a ResearchDocument with status='graphed', produces a
3-bullet executive summary + key_findings list, writes to MongoDB
collection `research_intelligence_summaries`.

impact_on_decision: HIGH (drives Plan 6 Key Findings card).

Uses VM107 services/llm_client.call_llm (synchronous wrapper) — model
selection is env-driven via LLM_MODEL/LLM_API_KEY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.research import storage


_PROMPT_TEMPLATE = """\
You are summarising a macroeconomic research document for a per-indicator
Research Hub. Produce EXACTLY 3 bullets of executive summary, then a
KEY_FINDINGS section listing 2-6 normalised key-finding tags.

Title: {title}
Indicators: {indicators}
Tier: {tier}

Text:
{body}

Format your output verbatim as:
- <bullet 1>
- <bullet 2>
- <bullet 3>
KEY_FINDINGS:
- <tag_1>
- <tag_2>
...
"""


@dataclass(frozen=True)
class SummaryResult:
    doc_id: str
    indicator_id: str
    summary_bullets: list[str]
    key_findings: list[str]


def _parse_llm_response(text: str) -> tuple[list[str], list[str]]:
    """Parse the canonical 3-bullet + KEY_FINDINGS shape."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bullets: list[str] = []
    findings: list[str] = []
    mode = "bullets"
    for ln in lines:
        if ln.upper().startswith("KEY_FINDINGS"):
            mode = "findings"
            continue
        if ln.startswith("- "):
            payload = ln[2:].strip()
            if mode == "bullets":
                bullets.append(payload)
            else:
                findings.append(payload)
    return bullets[:3], findings


class SummarisationAgent:
    """REQ-92-6 — summarises ResearchDocument → 3 bullets + key_findings."""

    def __init__(self, llm_caller: Any | None = None) -> None:
        self._llm = llm_caller

    def _call_llm(self, prompt: str) -> str:
        if self._llm is not None:
            return self._llm(prompt)
        # Lazy import so tests can monkeypatch services.llm_client.call_llm
        # without forcing litellm presence.
        from services import llm_client

        return llm_client.call_llm(prompt)

    def process(self, doc: Any) -> SummaryResult:
        # Doc may be Django model OR dataclass OR dict — read defensively.
        document_id = getattr(doc, "document_id", None) or doc["document_id"]
        indicators = getattr(doc, "indicators", None) or doc.get("indicators", [])
        if not indicators:
            raise ValueError(
                f"SummarisationAgent received doc {document_id} with no indicators; "
                "should be filtered out upstream (status='graphed' guarantees indicators)"
            )
        tier = getattr(doc, "tier", None) or doc.get("tier")
        title = getattr(doc, "title", None) or doc.get("title", "")
        body = getattr(doc, "body", None) or doc.get("body", "")

        prompt = _PROMPT_TEMPLATE.format(
            title=title, indicators=indicators, tier=tier, body=body
        )
        raw = self._call_llm(prompt)
        bullets, findings = _parse_llm_response(raw)
        if len(bullets) < 3:
            # Coerce up to exactly 3 bullets — pad with a placeholder so the
            # downstream contract holds. Plan 6 UI shows N bullets gracefully.
            bullets = (bullets + ["(no further detail)"] * 3)[:3]
        if not findings:
            findings = ["unclassified"]

        result = SummaryResult(
            doc_id=document_id,
            indicator_id=indicators[0],
            summary_bullets=list(bullets),
            key_findings=list(findings),
        )

        storage.write_summary(
            doc_id=result.doc_id,
            indicator_id=result.indicator_id,
            summary=result.summary_bullets,
            key_findings=result.key_findings,
            tier=tier,
            title=title,
        )

        return result
