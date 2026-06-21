"""Phase 89 Wave 3 — B13 Contradiction Engine package.

Exports:
  - ContradictionEngine: B13 service (detect_divergence, grade_severity, active_blocking,
                          increment_contradicting_count, write_contradiction)
  - SeverityResult: Named result from severity grader (severity, triggers_fired,
                    ui_surface, downstream_confidence_delta)
  - ContradictionArtifact: Pydantic model matching macro_contradictions SQL schema
"""
from .contradiction_engine import ContradictionArtifact, ContradictionEngine
from .severity_grader import SeverityResult, grade_severity

__all__ = [
    "ContradictionEngine",
    "ContradictionArtifact",
    "SeverityResult",
    "grade_severity",
]
