"""Phase 94-06 — Chief Economist Synthesizer (Router+Synthesizer §J).

Composes a natural-language user-facing response from a list of typed
:class:`SpecialistResponse` envelopes. The synthesizer NEVER invents
facts — every paragraph carries an attribution marker pointing back to
the specialist whose response it is grounded in (consumed by Phase 71
Evidence Drawer).

Confidence aggregation is **citation-weighted** (per §J locked decision)
— specialists with more grounding citations carry more weight than
specialists with thin evidence. Simple arithmetic averages would let
weakly-grounded outliers drag the answer down.

Graceful degradation per §J: if a specialist returns ``confidence <= 0``
(treated as an error sentinel) the synthesizer continues with the rest
and records an explicit limitation note in ``sections["limitations"]``.

Output structure follows the §I locked response shape:

    Answer → Evidence → Supporting Indicators → Research →
    Confidence → Alternative Views → Next Questions
"""

from __future__ import annotations

import logging
from typing import Iterable

from contracts.economic_intelligence.specialist_response import SpecialistResponse

logger = logging.getLogger(__name__)


# Sentinel — specialist responses with confidence <= ERROR_THRESHOLD are
# treated as failures and excluded from synthesis (graceful degradation §J).
_ERROR_THRESHOLD = 0.0

# Min citations per specialist for the weighted average to remain stable —
# specialists with zero citations get weight=1 (still counted, just not amplified).
_MIN_WEIGHT_PER_SPECIALIST = 1


class ChiefEconomistSynthesizer:
    """Composes specialist outputs into the §I locked response structure."""

    AGENT_ID = "vm107.chief_economist_synthesizer"

    def synthesize(
        self,
        specialist_responses: Iterable[SpecialistResponse],
        query: str,
        context: dict | None = None,
        specialist_ids: list[str] | None = None,
    ) -> dict:
        """Compose the §I locked response from specialist outputs.

        ``specialist_ids`` (optional) is a list of agent_ids parallel to
        ``specialist_responses`` for attribution marker generation. If
        omitted, the synthesizer uses positional indices as attribution.
        """
        responses = list(specialist_responses)
        ids = list(specialist_ids) if specialist_ids is not None else [
            f"specialist_{i}" for i in range(len(responses))
        ]
        if len(ids) != len(responses):
            raise ValueError(
                f"specialist_ids length ({len(ids)}) must match specialist_responses "
                f"length ({len(responses)})"
            )

        pairs = list(zip(responses, ids))
        # Split into usable vs errored — graceful degradation per §J.
        usable = [(r, i) for r, i in pairs if r.confidence > _ERROR_THRESHOLD]
        errored = [(r, i) for r, i in pairs if r.confidence <= _ERROR_THRESHOLD]

        confidence = _weighted_confidence(usable)

        sections = {
            "answer": _compose_answer(usable, query),
            "evidence": _compose_evidence(usable),
            "supporting_indicators": _extract_indicators(usable),
            "research": _extract_research(usable),
            "confidence": confidence,
            "alternative_views": _extract_alternatives(usable),
            "next_questions": _suggest_followups(usable, context or {}),
            "limitations": _compose_limitations(usable, errored),
            "_paragraph_attribution": _build_attribution_map(usable),
        }
        return sections


# ─────────────────────────────────────────────────────────── confidence math


def _weighted_confidence(usable: list[tuple[SpecialistResponse, str]]) -> float:
    """Citation-weighted average confidence per §J locked decision.

    Each specialist's confidence is weighted by ``max(len(citations), 1)``
    so weakly-grounded specialists don't drag the answer down disproportionately.
    A simple arithmetic mean would be vulnerable to a single noisy specialist
    with low confidence + 0 citations.
    """
    if not usable:
        return 0.0
    total_weight = 0.0
    weighted_sum = 0.0
    for r, _ in usable:
        weight = max(len(r.citations), _MIN_WEIGHT_PER_SPECIALIST)
        total_weight += weight
        weighted_sum += r.confidence * weight
    return weighted_sum / total_weight if total_weight else 0.0


# ─────────────────────────────────────────────────────────── prose composition


def _compose_answer(usable: list[tuple[SpecialistResponse, str]], query: str) -> str:
    if not usable:
        return "No specialists were available to answer this question."
    # Use first specialist's answer as the lead paragraph + concise stitches
    # from the remaining specialists. Deterministic Wave 3b composition; 94-07
    # may swap in LLM completion behind this surface.
    lead_resp, lead_id = usable[0]
    paragraphs = [f"{lead_resp.answer}  <!-- specialist:{lead_id} -->"]
    for resp, ident in usable[1:]:
        # Take the first sentence of subsequent specialists to avoid duplication.
        sentence = resp.answer.split(".")[0].strip()
        if sentence:
            paragraphs.append(f"{sentence}.  <!-- specialist:{ident} -->")
    return "\n\n".join(paragraphs)


def _compose_evidence(usable: list[tuple[SpecialistResponse, str]]) -> list[dict]:
    """Flatten each specialist's evidence list with attribution."""
    flat: list[dict] = []
    for r, ident in usable:
        for ev in r.evidence:
            flat.append({**ev, "_specialist": ident})
    return flat


def _extract_indicators(usable: list[tuple[SpecialistResponse, str]]) -> list[str]:
    """Extract indicator citations (prefix 'ref:indicator:') from all responses."""
    out: list[str] = []
    seen: set[str] = set()
    for r, _ in usable:
        for cit in r.citations:
            if cit.startswith("ref:indicator:") and cit not in seen:
                out.append(cit)
                seen.add(cit)
            elif not cit.startswith("ref:") and cit not in seen:
                # Bare indicator IDs from Wave 3a specialists are still useful.
                out.append(cit)
                seen.add(cit)
    return out


def _extract_research(usable: list[tuple[SpecialistResponse, str]]) -> list[str]:
    """Extract research citations (prefix 'ref:episode:' or 'ref:research:')."""
    out: list[str] = []
    for r, _ in usable:
        for cit in r.citations:
            if cit.startswith(("ref:episode:", "ref:research:")):
                out.append(cit)
    return out


def _extract_alternatives(usable: list[tuple[SpecialistResponse, str]]) -> list[str]:
    """Pull alternative-view caveats from specialist limitations.

    Wave 3b uses a heuristic — any limitation mentioning "but", "however",
    or "alternative" is treated as an alternative view. 94-07 may add a
    dedicated SpecialistResponse field.
    """
    out: list[str] = []
    keywords = ("but", "however", "alternative", "alternatively", "counter")
    for r, ident in usable:
        for lim in r.limitations:
            if any(kw in lim.lower() for kw in keywords):
                out.append(f"{lim}  <!-- specialist:{ident} -->")
    return out


def _suggest_followups(
    usable: list[tuple[SpecialistResponse, str]], context: dict
) -> list[str]:
    """Suggest 2-3 next questions the user could ask.

    Wave 3b uses related_entities — each unique entity becomes a "Tell me
    about <entity>" suggestion. Capped at 3.
    """
    seen: set[str] = set()
    suggestions: list[str] = []
    for r, _ in usable:
        for ent in r.related_entities:
            if ent in seen:
                continue
            seen.add(ent)
            suggestions.append(f"Tell me more about {ent}")
            if len(suggestions) >= 3:
                return suggestions
    return suggestions


def _compose_limitations(
    usable: list[tuple[SpecialistResponse, str]],
    errored: list[tuple[SpecialistResponse, str]],
) -> list[str]:
    out: list[str] = []
    # Pull through specialist-level limitations.
    for r, ident in usable:
        for lim in r.limitations:
            out.append(f"{lim}  <!-- specialist:{ident} -->")
    # Explicit note for errored specialists (graceful degradation §J).
    for r, ident in errored:
        out.append(
            f"{ident} unavailable; answer excludes {ident} analysis."
        )
    return out


def _build_attribution_map(
    usable: list[tuple[SpecialistResponse, str]]
) -> dict[str, str]:
    """Per-paragraph attribution map for §I Evidence Drawer.

    Maps a stable paragraph-index string to the specialist agent_id that
    produced it. The frontend consumes this to render the citation popover.
    """
    return {f"p{i}": ident for i, (_, ident) in enumerate(usable)}


__all__ = ["ChiefEconomistSynthesizer"]
