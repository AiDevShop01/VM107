"""Phase 173 (D-05) — MacroContradictionDetector thin agent.

Binds the built core/contradiction/ContradictionEngine; reimplements NO
detection/grading/persistence logic (all owned by the engine).
"""

from agents.macro_contradiction_detector.agent import (
    MacroContradictionDetector,
    emit_for_release,
)

__all__ = ["MacroContradictionDetector", "emit_for_release"]
