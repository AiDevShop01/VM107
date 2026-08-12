"""SC-2 (P7) — chat-model-call SLO record.

Reads the ``_slo_start`` stamp planted by ``chat_model_call_before/_90_slo_start``
and records the elapsed model-call latency (ms) into ``SLORegistry('model_call')``.
Additive/non-invasive — ``core/agents/model_calls.py`` is UNTOUCHED (T-139-07).

No-op guard (T-139-08): if the before-stamp is absent (after-hook fired without a
paired before), record nothing and raise nothing — the model-call path must never
break on a missing SLO stamp.
"""
import time

from helpers.extension import Extension


class ChatModelCallSloRecord(Extension):
    async def execute(self, **kwargs):
        if not self.agent:
            return
        call_data: dict = kwargs.get("call_data", {})
        start = call_data.get("_slo_start")
        if start is None:
            return
        from core.observability.slo_registry import SLORegistry

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        SLORegistry.get_shared_instance().record("model_call", elapsed_ms)
