"""Re-export of the PersistNarrative Tool wrapper.

The CANONICAL class lives in persist_narrative.py alongside the standalone
PersistNarrativeTool so agent.get_tool('persist_narrative') resolves it
(agent.get_tool resolves by filename: load_classes_from_file('python/tools/persist_narrative.py', Tool)).

This module exists for callers who want a clear `_tool.py` suffix import.
It is NOT consulted by agent.get_tool — do not move the canonical class here.
"""
from .persist_narrative import PersistNarrative

__all__ = ["PersistNarrative"]
