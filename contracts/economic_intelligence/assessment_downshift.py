"""Phase 169-03 (D-01 / D-03, AGV-10) — DomainAssessment -> SpecialistResponse downshift.

The `DomainAssessment ⊇ SpecialistResponse` relationship (D-01) is realised HERE as an
explicit, tested **projection** — NOT inheritance. `SpecialistResponse` stays byte-untouched
(frozen, `extra="forbid"`); the enriched `DomainAssessment` becomes the source of truth while
the chief_economist_synthesizer's existing `SpecialistResponse` consumer keeps working.

Dependency direction (D-03): this adapter is the ONLY place BOTH types are imported —
`DomainAssessment` from shared `fingpt_core.contracts.assessment` and `SpecialistResponse`
from the VM107-local `contracts.economic_intelligence.specialist_response`. `fingpt_core`
NEVER imports a VM107 type (the reverse-dependency ban); the projection lives VM107-side.

Projection map (every SpecialistResponse field is derived from a DomainAssessment field):
- answer            <- deterministic one-line summary of horizon/level/momentum/surprise
- confidence        <- assessment.confidence.overall (the decomposed roll-up)
- citations         <- flattened, order-preserving, de-duplicated claim evidence_refs
- evidence          <- each Claim projected to an open dict (subject/predicate/object + refs)
- limitations       <- assessment.invalidation_conditions + a typed abstention caveat
- related_entities  <- domain / geography / optional sector cross-references
- schema_version    <- stays the SpecialistResponse default ("1"); the adapter never weakens it
"""

from __future__ import annotations

from typing import Any

# Shared enriched source contract (fingpt_core — dependency-free, D-03).
from fingpt_core.contracts.assessment import DomainAssessment

# VM107-local frozen target contract — stays UNTOUCHED (D-01). This adapter is the
# single place both contracts meet; fingpt_core never imports back the other way.
from contracts.economic_intelligence.specialist_response import SpecialistResponse


def _fmt(value: float | None) -> str:
    """Deterministic optional-float rendering ('n/a' for an unmeasured/Unknown value)."""
    return "n/a" if value is None else f"{value:+.2f}"


def _compose_answer(assessment: DomainAssessment) -> str:
    """A deterministic one-line summary of the current read (never LLM-generated).

    Summarises the separate level/momentum/surprise (never collapsed) plus horizon and
    the decomposed-confidence roll-up. Guaranteed non-empty so it satisfies the
    SpecialistResponse ``answer`` ``min_length=1`` constraint.
    """
    scope = assessment.domain
    if assessment.sector:
        scope = f"{scope} / {assessment.sector}"
    line = (
        f"{scope} in {assessment.geography_id} ({assessment.horizon.value}): "
        f"level {_fmt(assessment.level)}, momentum {_fmt(assessment.momentum)}, "
        f"surprise {_fmt(assessment.surprise)}; "
        f"confidence {assessment.confidence.overall:.2f}."
    )
    if assessment.abstention_outcome is not None:
        line += f" Abstained: {assessment.abstention_outcome.value}."
    return line


def _project_citations(assessment: DomainAssessment) -> list[str]:
    """Flatten every claim's evidence_refs into ordered, de-duplicated citation refs."""
    citations: list[str] = []
    seen: set[str] = set()
    for claim in assessment.claims:
        for ref in claim.evidence_refs:
            if ref not in seen:
                seen.add(ref)
                citations.append(ref)
    return citations


def _project_evidence(assessment: DomainAssessment) -> list[dict[str, Any]]:
    """Project each first-class Claim onto an open evidence dict (the §M open shape)."""
    return [
        {
            "claim_id": claim.claim_id,
            "claim_class": claim.claim_class.value,
            "subject": claim.subject,
            "predicate": claim.predicate,
            "object": claim.object,
            "horizon": claim.horizon.value,
            "confidence": claim.confidence,
            "evidence_refs": list(claim.evidence_refs),
            "contradicting_evidence_refs": list(claim.contradicting_evidence_refs),
            "assumptions": list(claim.assumptions),
            "invalidation_conditions": list(claim.invalidation_conditions),
            "generated_by": claim.generated_by,
        }
        for claim in assessment.claims
    ]


def _project_limitations(assessment: DomainAssessment) -> list[str]:
    """Human-readable caveats: assessment invalidation conditions + a typed abstention."""
    limitations: list[str] = list(assessment.invalidation_conditions)
    if assessment.abstention_outcome is not None:
        limitations.append(f"abstained: {assessment.abstention_outcome.value}")
    return limitations


def _project_related_entities(assessment: DomainAssessment) -> list[str]:
    """Cross-references — domain, geography (type:id), and optional sector."""
    related = [
        f"domain:{assessment.domain}",
        f"geography:{assessment.geography_type}:{assessment.geography_id}",
    ]
    if assessment.sector:
        related.append(f"sector:{assessment.sector}")
    return related


def to_specialist_response(assessment: DomainAssessment) -> SpecialistResponse:
    """Downshift an enriched `DomainAssessment` to the legacy `SpecialistResponse` (D-01/D-03).

    The returned object is a VALID `SpecialistResponse` — it passes that model's own frozen /
    ``extra="forbid"`` validation, so the projection cannot smuggle unknown fields or weaken
    the contract. Every SpecialistResponse field is derived from a DomainAssessment field (the
    ⊇ coverage locked by ``tests/contracts/test_assessment_downshift.py``). ``schema_version``
    is intentionally left at the SpecialistResponse default ("1") — the enriched
    ``assessment_schema_version`` is NOT projected onto it (the target contract is unchanged).
    """
    return SpecialistResponse(
        answer=_compose_answer(assessment),
        confidence=assessment.confidence.overall,
        citations=_project_citations(assessment),
        evidence=_project_evidence(assessment),
        limitations=_project_limitations(assessment),
        related_entities=_project_related_entities(assessment),
    )


__all__ = ["to_specialist_response"]
