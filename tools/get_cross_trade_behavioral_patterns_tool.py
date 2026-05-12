"""Re-export of the GetCrossTradeBehavioralPatterns Tool wrapper.

The CANONICAL class lives in get_cross_trade_behavioral_patterns.py alongside
the standalone GetCrossTradeBehavioralPatternsTool so
agent.get_tool('get_cross_trade_behavioral_patterns') resolves it
(agent.get_tool resolves by filename: load_classes_from_file('python/tools/get_cross_trade_behavioral_patterns.py', Tool)).

This module exists for callers who want a clear `_tool.py` suffix import.
It is NOT consulted by agent.get_tool — do not move the canonical class here.
"""
from .get_cross_trade_behavioral_patterns import GetCrossTradeBehavioralPatterns

__all__ = ["GetCrossTradeBehavioralPatterns"]
