"""Phase 139 / P7 (SC-2) — SLO capture regression lock.

Splits into two tiers so the host-clean fast loop touches ZERO heavy deps:

  HOST-CLEAN (no marker) — pure ``SLORegistry`` + the ``_slo_vitals`` builder
    (both import stdlib/redis only). Proves synthetic samples land with
    nearest-rank p50/p95 for ``tool_dispatch`` and ``model_call``, and that the
    telemetry publisher's additive vitals field carries them.

  requires_deps (Tier-2 venv) — the ``api/v1/telemetry/slo.py`` ApiHandler
    (imports ``helpers.api`` → flask) and the four model-call Extension hooks
    (import ``helpers.extension`` → simpleeval). Proves the X-API-KEY gate
    (T-139-06) and that a before→after hook pair records a ``model_call`` sample
    while an after-without-before is a safe no-op (T-139-08).

ALL ApiHandler / Extension imports are DEFERRED into the marked test bodies so
``-m "not requires_deps"`` collects and runs with zero heavy imports.

The ``reset_slo`` autouse (conftest) clears the shared SLORegistry per test.
"""
from __future__ import annotations

import asyncio

import pytest

from core.observability.slo_registry import SLORegistry


# ---------------------------------------------------------------------------
# HOST-CLEAN tier — pure SLORegistry + the vitals builder (no flask/simpleeval)
# ---------------------------------------------------------------------------


def test_tool_dispatch_samples_land_with_percentiles():
    """Synthetic tool_dispatch samples produce count + nearest-rank p50/p95."""
    reg = SLORegistry.get_shared_instance()
    for ms in range(1, 101):  # 1..100 ms
        reg.record("tool_dispatch", float(ms))

    snap = reg.snapshot()
    assert "tool_dispatch" in snap
    td = snap["tool_dispatch"]
    assert td["count"] == 100
    assert "p50" in td and "p95" in td
    # nearest-rank on 1..100: p50 index 49 -> 50, p95 index 94 -> 95
    assert td["p50"] == 50.0
    assert td["p95"] == 95.0


def test_model_call_samples_land_with_percentiles():
    """Synthetic model_call samples produce count + p50/p95 (independent path)."""
    reg = SLORegistry.get_shared_instance()
    for ms in (10.0, 20.0, 30.0, 40.0, 50.0):
        reg.record("model_call", ms)

    snap = reg.snapshot()
    assert "model_call" in snap
    mc = snap["model_call"]
    assert mc["count"] == 5
    assert mc["p50"] > 0.0
    assert mc["p95"] > 0.0
    # paths are isolated — model_call must not leak tool_dispatch samples
    assert "tool_dispatch" not in snap


def test_vitals_builder_carries_slo_paths():
    """The telemetry publisher's additive `slo` field carries the SLO paths."""
    from emitters.agent_telemetry_snapshot_publisher import _slo_vitals

    reg = SLORegistry.get_shared_instance()
    reg.record("recall", 42.0)
    reg.record("tool_dispatch", 5.0)

    vitals = _slo_vitals()
    assert isinstance(vitals, dict)
    assert "paths" in vitals
    assert "recall" in vitals["paths"]
    assert "tool_dispatch" in vitals["paths"]
    assert vitals["paths"]["recall"]["count"] == 1
    # dep_down_count is present (reset_source_health autouse -> 0 here)
    assert "dep_down_count" in vitals
    assert vitals["dep_down_count"] == 0


# ---------------------------------------------------------------------------
# requires_deps tier — ApiHandler (flask) + Extension hooks (simpleeval)
# ---------------------------------------------------------------------------


@pytest.mark.requires_deps
def test_slo_endpoint_requires_api_key_and_shape():
    """SLO ApiHandler gates on X-API-KEY and returns {path:{p50,p95,count,slo_ok}}."""
    # Deferred import — helpers.api pulls flask (Tier-2 only).
    import importlib.util
    import os

    _here = os.path.dirname(__file__)
    _slo_path = os.path.abspath(os.path.join(_here, "..", "..", "api", "v1", "telemetry", "slo.py"))
    spec = importlib.util.spec_from_file_location("_p7_slo_endpoint", _slo_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    handler_cls = mod.TelemetrySloHandler
    # T-139-06: no unauthenticated exposure.
    assert handler_cls.requires_api_key() is True
    assert handler_cls.requires_auth() is False
    assert "GET" in handler_cls.get_methods()

    # Seed a sample so process() returns a populated, correctly-shaped snapshot.
    reg = SLORegistry.get_shared_instance()
    reg.record("recall", 120.0)

    # ApiHandler.__init__(app, thread_lock) — both stored, unused by process().
    handler = handler_cls(None, None)
    result = asyncio.run(handler.process({}, None))
    assert isinstance(result, dict)
    assert "recall" in result
    entry = result["recall"]
    assert set(entry.keys()) == {"p50", "p95", "count", "slo_ok"}
    # recall p95=120ms < 300ms budget -> slo_ok True
    assert entry["slo_ok"] is True


@pytest.mark.requires_deps
def test_model_call_hooks_record_sample():
    """before→after hook pair records a model_call sample; after-only is a no-op."""
    # Deferred imports — helpers.extension pulls simpleeval (Tier-2 only).
    import importlib.util
    import os

    def _load(rel: str, name: str):
        _here = os.path.dirname(__file__)
        path = os.path.abspath(os.path.join(_here, "..", "..", "extensions", "python", rel))
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore[union-attr]
        return m

    before_mod = _load("chat_model_call_before/_90_slo_start.py", "_p7_chat_before")
    after_mod = _load("chat_model_call_after/_90_slo_record.py", "_p7_chat_after")

    class _FakeAgent:
        pass

    before = before_mod.ChatModelCallSloStart(agent=_FakeAgent())
    after = after_mod.ChatModelCallSloRecord(agent=_FakeAgent())

    reg = SLORegistry.get_shared_instance()

    # before → after records exactly one model_call sample
    call_data: dict = {}
    asyncio.run(before.execute(call_data=call_data))
    assert "_slo_start" in call_data
    asyncio.run(after.execute(call_data=call_data))
    snap = reg.snapshot()
    assert snap.get("model_call", {}).get("count") == 1

    # after WITHOUT before (missing _slo_start) is a safe no-op (T-139-08)
    reg.clear()
    asyncio.run(after.execute(call_data={}))
    assert "model_call" not in reg.snapshot()


# ---------------------------------------------------------------------------
# integration tier — cross-process /metrics scrape (AZI-05, Phase 154)
# ---------------------------------------------------------------------------


@pytest.mark.requires_deps
def test_metrics_endpoint_exposes_cross_process_histogram():
    """AZI-05 (RED until 154-05): the vm107 agent process must export a
    Prometheus histogram ``vm107_slo_latency_ms`` (with a ``path`` label) over
    a cross-process ``/metrics`` endpoint — the fix for the publisher's empty
    ``paths: {}`` (its in-process SLORegistry copy is always empty).

    This is RED today: no ``prometheus_client`` histogram is wired and no
    ``/metrics`` server listens on the metrics port, so the scrape either
    connection-refuses or the body lacks the metric. It flips GREEN when 154-05
    lands the histogram + endpoint. Marked ``requires_deps`` so the host-clean
    fast loop (``-m "not requires_deps"``) skips it.
    """
    # Deferred stdlib imports keep host-clean collection dep-free.
    import os
    import urllib.request

    # Canonical SLO paths (api/v1/telemetry/slo.py budgets): recall <300ms,
    # tool_dispatch <100ms, model_call <30000ms. Drive one sample per path so a
    # correctly-wired histogram has something to export.
    reg = SLORegistry.get_shared_instance()
    reg.record("recall", 42.0)
    reg.record("tool_dispatch", 5.0)
    reg.record("model_call", 1234.0)

    metrics_url = os.environ.get("VM107_METRICS_URL", "http://localhost:9107/metrics")

    # RED today: connection refused (no server) OR metric absent. Either way the
    # assertions below fail — that is the intended pending-AZI-05 signal.
    with urllib.request.urlopen(metrics_url, timeout=5) as resp:  # noqa: S310 (fixed localhost target)
        body = resp.read().decode("utf-8", "replace")

    # The literal histogram metric name AZI-05 must export...
    assert "vm107_slo_latency_ms" in body, (
        "cross-process histogram vm107_slo_latency_ms not found at "
        f"{metrics_url} — AZI-05 (154-05) not yet delivered"
    )
    # ...carrying a per-path label so p50/p95 are broken out by SLO path.
    assert "path=" in body, (
        "vm107_slo_latency_ms present but has no `path=` label — the histogram "
        "must be labelled by SLO path (recall/tool_dispatch/model_call)"
    )
