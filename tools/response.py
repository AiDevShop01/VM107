import logging

from helpers.tool import Tool, Response

_LOGGER = logging.getLogger("fingpt.tools.response")
_CANONICAL_KEYS = ("text", "message")
_FALLBACK_KEYS = ("response", "output", "content")


class ResponseTool(Tool):

    async def execute(self, **kwargs):
        text = None
        for key in _CANONICAL_KEYS:
            if key in self.args:
                text = self.args[key]
                break
        if text is None:
            for key in _FALLBACK_KEYS:
                if key in self.args:
                    _LOGGER.warning(
                        "response tool: LLM used non-canonical key '%s'; expected 'text' (BUG-15 fallback)",
                        key,
                    )
                    text = self.args[key]
                    break
        if text is None:
            _LOGGER.error(
                "response tool: no recognized key in args; available=%s (returning str(args) to avoid KeyError)",
                list(self.args.keys()),
            )
            text = str(self.args)
        return Response(message=text, break_loop=True)

    async def before_execution(self, **kwargs):
        # self.log = self.agent.context.log.log(type="response", heading=f"{self.agent.agent_name}: Responding", content=self.args.get("text", ""))
        # don't log here anymore, we have the live_response extension now
        pass

    async def after_execution(self, response, **kwargs):
        # do not add anything to the history or output

        if self.loop_data and "log_item_response" in self.loop_data.params_temporary:
            log = self.loop_data.params_temporary["log_item_response"]
            log.update(finished=True)  # mark the message as finished
