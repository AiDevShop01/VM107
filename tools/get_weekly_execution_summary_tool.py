"""Re-export of the GetWeeklyExecutionSummary Tool wrapper.

The CANONICAL class lives in get_weekly_execution_summary.py alongside
the standalone GetWeeklyExecutionSummaryTool so
agent.get_tool('get_weekly_execution_summary') resolves it
(agent.get_tool resolves by filename: load_classes_from_file('python/tools/get_weekly_execution_summary.py', Tool)).

This module exists for callers who want a clear `_tool.py` suffix import.
It is NOT consulted by agent.get_tool — do not move the canonical class here.
"""
from .get_weekly_execution_summary import GetWeeklyExecutionSummary

__all__ = ["GetWeeklyExecutionSummary"]
