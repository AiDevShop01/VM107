"""Re-export of the GetBehavioralEdges Tool wrapper.

The CANONICAL class lives in get_behavioral_edges.py alongside the standalone
GetBehavioralEdgesTool so agent.get_tool('get_behavioral_edges') resolves it
(agent.get_tool resolves by filename: load_classes_from_file('python/tools/get_behavioral_edges.py', Tool)).

This module exists for callers who want a clear `_tool.py` suffix import.
It is NOT consulted by agent.get_tool — do not move the canonical class here.
"""
from .get_behavioral_edges import GetBehavioralEdges

__all__ = ["GetBehavioralEdges"]
