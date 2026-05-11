"""VM107 replay tools — Phase 59 CONTEXT §18.

Three orthogonal typed surfaces for replay cognition:
- lookup_replay_artifact   → ReplayArtifactMeta (capability_type=replay_lookup)
- fetch_replay_frame       → ReplayFrame        (capability_type=replay_frame)
- fetch_replay_chart_slice → ChartSlice         (capability_type=replay_chart)

All tools follow Phase 39 typed-API discipline:
  - NO filesystem reads
  - NO direct DB access
  - Only HTTP over typed VM100 internal endpoints
  - timeout=30 (Pitfall 11)
  - 503/504 → ToolError (NOT raise) (Pitfall 11)
"""
from tools.replay.lookup_replay_artifact import ToolError, lookup_replay_artifact
from tools.replay.fetch_replay_frame import fetch_replay_frame
from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice

__all__ = [
    "lookup_replay_artifact",
    "fetch_replay_frame",
    "fetch_replay_chart_slice",
    "ToolError",
]
