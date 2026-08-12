"""VM107 ApiHandler — GET /api/v1/telemetry/slo

Surfaces the in-app p50/p95 SLO capture (Phase 139 / P7, SC-2, decision D-01)
through the existing telemetry HTTP surface — reuse-first, zero new infra.
Reads ``SLORegistry.get_shared_instance().snapshot()`` in-process and reshapes it
to ``{path: {p50, p95, count, slo_ok}}`` so a "degraded but healthy-looking" state
(recall/tool-dispatch/model-call latency drifting past its budget) becomes visible.

The percentiles are computed in-process by ``core/observability/slo_registry.py``
(bounded deque + nearest-rank); this endpoint is a thin read-and-classify surface.

Auth: X-API-KEY required (same service-to-service contract as ``cost.py`` /
``ai_routing`` — ASVS V2). Internal latency/health data must NOT be exposed
unauthenticated (T-139-06).

Failure mode: any error → empty ``{}`` snapshot (cost.py graceful-degrade idiom).
"""
from __future__ import annotations

import logging
from typing import Any

from helpers.api import ApiHandler, Response

log = logging.getLogger(__name__)


# Per-path SLO budgets (ms). recall p95 < 300 ms is the spec target (CONTEXT/
# RESEARCH); tool_dispatch is resolution+load so it should be sub-100 ms; the
# model-call budget is the timeout-adherence bound (model calls are inherently
# slow — the SLO is "within the timeout", not "fast"). A path with no budget
# reports slo_ok=None (unknown) rather than a misleading pass/fail.
_SLO_TARGETS_MS: dict[str, float] = {
    "recall": 300.0,
    "tool_dispatch": 100.0,
    "model_call": 30000.0,
}


def _slo_ok(path: str, p95: float) -> bool | None:
    """True/False when the path has a budget, None when it does not."""
    target = _SLO_TARGETS_MS.get(path)
    if target is None:
        return None
    return p95 <= target


def _reshape(snapshot: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """Reshape ``{path: {count,p50,p95}}`` → ``{path: {p50,p95,count,slo_ok}}``."""
    out: dict[str, dict[str, Any]] = {}
    for path, stats in snapshot.items():
        p95 = stats.get("p95", 0.0)
        out[path] = {
            "p50": stats.get("p50", 0.0),
            "p95": p95,
            "count": stats.get("count", 0),
            "slo_ok": _slo_ok(path, p95),
        }
    return out


class TelemetrySloHandler(ApiHandler):
    """GET /api/v1/telemetry/slo — in-app p50/p95 latency SLO snapshot."""

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: dict, request) -> dict | Response:
        try:
            from core.observability.slo_registry import SLORegistry

            snapshot = SLORegistry.get_shared_instance().snapshot()
            return _reshape(snapshot)
        except Exception as exc:  # noqa: BLE001
            log.exception("telemetry.slo.build_failed: %s", exc)
            return {}
