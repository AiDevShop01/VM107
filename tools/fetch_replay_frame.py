"""Agent Zero Tool wrapper for fetch_replay_frame.

BUG-14 fix: flat-discovery wrapper at top-level tools/ path. Mirrors
lookup_replay_artifact.py pattern.
"""
from __future__ import annotations

import json
from uuid import UUID

from helpers.tool import Response, Tool
from tools.replay.fetch_replay_frame import fetch_replay_frame as _fetch_replay_frame_fn
from tools.replay.lookup_replay_artifact import ToolError


def _maybe_int(value, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class FetchReplayFrame(Tool):
    """LLM-callable: fetch_replay_frame(execution_id, occurred_at, sequence_number, ...)."""

    async def execute(self, **kwargs) -> Response:
        args = self.args or {}
        try:
            execution_id = UUID(str(args["execution_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            return Response(
                message=json.dumps({"error": f"invalid/missing execution_id: {exc}"}),
                break_loop=False,
            )

        occurred_at = str(args.get("occurred_at", "") or "")
        sequence_number = _maybe_int(args.get("sequence_number"), default=1) or 1
        truth_mode = str(args.get("truth_mode", "HISTORICAL") or "HISTORICAL")
        replay_version = _maybe_int(args.get("replay_version"))

        result = _fetch_replay_frame_fn(
            execution_id=execution_id,
            occurred_at=occurred_at,
            sequence_number=sequence_number,
            truth_mode=truth_mode,
            replay_version=replay_version,
        )
        if isinstance(result, ToolError):
            payload = {"error": result.code, "message": result.message}
        else:
            payload = result.model_dump(mode="json")

        return Response(message=json.dumps(payload), break_loop=False)
