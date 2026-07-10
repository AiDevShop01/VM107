"""Agent Zero Tool wrapper for the replay-artifact lookup function.

BUG-14 fix: Agent Zero's tool resolver (`get_tool` in agent.py) does a flat lookup
at `tools/<name>.py` — it does not walk subdirectories. The underlying typed
function lives at `tools/replay/lookup_replay_artifact.py`. This file exposes a
Tool subclass at the top-level `tools/` path so the reader sub-profile can
actually find it.

The wrapper does no business logic — it parses args, calls the typed function,
and returns the result as a Tool Response.
"""
from __future__ import annotations

import json
from uuid import UUID

from helpers.tool import Response, Tool
from tools.replay.lookup_replay_artifact import (
    ToolError,
    lookup_replay_artifact as _lookup_replay_artifact_fn,
)


class LookupReplayArtifact(Tool):
    """LLM-callable: lookup_replay_artifact(execution_id=<uuid>, replay_version=<int|null>)."""

    async def execute(self, **kwargs) -> Response:
        args = self.args or {}
        execution_id_raw = args.get("execution_id")
        if not execution_id_raw:
            return Response(
                message=json.dumps({"error": "missing execution_id"}),
                break_loop=False,
            )
        try:
            execution_id = UUID(str(execution_id_raw))
        except (ValueError, TypeError) as exc:
            return Response(
                message=json.dumps({"error": f"invalid execution_id: {exc}"}),
                break_loop=False,
            )

        replay_version = args.get("replay_version")
        if isinstance(replay_version, str) and replay_version.strip():
            try:
                replay_version = int(replay_version)
            except ValueError:
                replay_version = None
        elif replay_version is not None and not isinstance(replay_version, int):
            replay_version = None

        result = _lookup_replay_artifact_fn(execution_id, replay_version)
        if isinstance(result, ToolError):
            payload = {"error": result.code, "message": result.message}
        else:
            payload = result.model_dump(mode="json")

        return Response(message=json.dumps(payload), break_loop=False)
