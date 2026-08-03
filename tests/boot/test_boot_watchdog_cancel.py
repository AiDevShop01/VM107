"""Phase 132 Plan 01 — SC-2 RED unit test (watchdog cancels on the ready path).

The whole-boot watchdog is armed via `faulthandler.dump_traceback_later(t, exit=True)`
at the top of run_ui.run(). Pitfall 2: a slow-but-healthy boot must NOT be killed — the
timer has to be cancelled once readiness is reached. The ready path runs through
`helpers.server_startup.StartupMonitor.mark_ready()`.

This test spies on `faulthandler.cancel_dump_traceback_later` and drives the ready path,
asserting the cancel was invoked. RED until Wave 1 (132-02) wires
`cancel_dump_traceback_later()` into the ready path (mark_ready / the health-probe
success branch). Imports are lazy inside the test body so collection never errors.
"""
from __future__ import annotations

import pytest


@pytest.mark.quick
def test_mark_ready_cancels_boot_watchdog(monkeypatch):
    """Driving StartupMonitor.mark_ready() cancels the faulthandler boot watchdog."""
    import faulthandler

    from helpers.server_startup import StartupMonitor

    calls = {"cancel": 0}

    def _spy_cancel():
        calls["cancel"] += 1

    # Spy on the stdlib cancel used to disarm the boot watchdog.
    monkeypatch.setattr(
        faulthandler, "cancel_dump_traceback_later", _spy_cancel, raising=True
    )

    monitor = StartupMonitor(
        bind_host="0.0.0.0",
        probe_host="127.0.0.1",
        port=80,
        attempt=1,
        max_attempts=1,
        timeout_seconds=90,
    )

    # Drive the readiness transition that a healthy boot reaches.
    monitor.mark_ready("health_probe")

    # RED until 132-02 wires cancel_dump_traceback_later() into the ready path.
    assert calls["cancel"] >= 1, (
        "mark_ready() must cancel the faulthandler boot watchdog so a slow-but-healthy "
        "boot is not killed (Pitfall 2)"
    )
