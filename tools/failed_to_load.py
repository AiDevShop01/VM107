from helpers.tool import Tool, Response


class FailedToLoad(Tool):
    """Sentinel for a tool whose file EXISTS on the resolution path but failed to load.

    Distinct from ``Unknown`` (no file found anywhere). ``agent.get_tool`` returns this
    when a tool path was resolved but every load attempt raised — the caught exception
    (with traceback + resolved path) is logged at WARN server-side. The agent-visible
    refusal below tells the model the tool exists but could not be loaded; it never
    carries the raw traceback or any infrastructure detail (T-135-02 no-leak).
    """

    async def execute(self, **kwargs):
        return Response(
            message=self.agent.read_prompt(
                "fw.tool_failed_to_load.md", tool_name=self.name
            ),
            break_loop=False,
        )
