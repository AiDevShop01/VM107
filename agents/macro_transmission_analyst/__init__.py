"""Phase 87 Wave 2 — macro_transmission_analyst event-driven agent package.

Public surface:
  - MacroTransmissionAnalyst        — Phase 36 AgentRunner-integrated class
  - TransmissionNarrationSkill      — narration prompt + hard-assertion regex gate
  - NarrationFailedAfterRetry       — raised after one retry on regex failure
  - TransmissionAnalysisResult      — dataclass returned by .run()
"""
from .agent import MacroTransmissionAnalyst, TransmissionAnalysisResult
from .skill_transmission_narration import (
    NarrationFailedAfterRetry,
    TransmissionNarrationSkill,
)

__all__ = [
    "MacroTransmissionAnalyst",
    "TransmissionAnalysisResult",
    "TransmissionNarrationSkill",
    "NarrationFailedAfterRetry",
]
