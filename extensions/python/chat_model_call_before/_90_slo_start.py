"""SC-2 (P7) — chat-model-call SLO start stamp.

Stamps a ``perf_counter()`` start time onto ``call_data`` so the paired
``chat_model_call_after/_90_slo_record`` extension can record the elapsed
model-call latency into ``SLORegistry('model_call')`` — WITHOUT editing
``core/agents/model_calls.py`` (the timing rides the existing before/after
extension hooks; the model-call path is unchanged, T-139-07).

``_90_`` prefix so the SLO stamp runs LAST in the before-chain (after router /
subprofile / thinking-mode extensions), keeping the timed window tight to the
actual model call.
"""
import time

from helpers.extension import Extension


class ChatModelCallSloStart(Extension):
    async def execute(self, **kwargs):
        if not self.agent:
            return
        call_data: dict = kwargs.get("call_data", {})
        call_data["_slo_start"] = time.perf_counter()
