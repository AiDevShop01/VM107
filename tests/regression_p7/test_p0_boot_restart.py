"""Phase 139 P7 — P0 boot self-restart watchdog regression (SC-1).

Guards (single-source `guarded_commits.GUARDED_COMMITS['test_p0_boot_restart']`):
  fe21a20  — feat(132-02): cancel the whole-boot faulthandler watchdog on the
             ready path (StartupMonitor.mark_ready) so a slow-but-healthy boot is
             NOT killed. This is the load-bearing fix: reverting it removes the
             cancel from mark_ready, so a healthy boot would be self-killed → RED.
  be52083  — fix(132-03): floor the MCP init_timeout default + last usage site
             (keeps the whole-boot bound meaningful).

What this locks (OQ3, 139-RESEARCH.md L435-439):
  (a) ARMED-WITH-BOUND: run_ui.run() arms the whole-boot watchdog via
      faulthandler.dump_traceback_later(BOOT_WATCHDOG_SECONDS, exit=True) BEFORE any
      boot work — exit=True is what makes a wedged boot os._exit(1) → supervisor
      self-restart. The bound is the configured A0_BOOT_WATCHDOG_SECONDS (floored 30).
  (b) NOT-CANCELLED-ON-HANG: the watchdog is disarmed ONLY on the ready path
      (StartupMonitor.mark_ready → faulthandler.cancel_dump_traceback_later). When
      init hangs, mark_ready is never reached → the watchdog stays armed → it fires
      → self-restart. A logic assertion, not a real process kill; the live restart is
      covered by the V-02 docker-exec smoke.

Tier-2 note: the behavioral assertions import `run_ui` / `helpers.server_startup`,
whose import chain pulls aiohttp/simpleeval/litellm (Python 3.12 + the pinned deps)
that are absent on the host py3.11 interpreter. They are therefore
`@pytest.mark.requires_deps` and run under the Tier-2 venv (VM107/.venv, python3.12);
the host-clean fast loop (`-m "not requires_deps"`) runs only the guarded-commit
annotation self-check below. All heavy imports are DEFERRED into the test bodies so
host-clean collection never hits the ModuleNotFound wall (no top-level heavy import).
"""
from __future__ import annotations

import pytest

from tests.regression_p7.guarded_commits import GUARDED_COMMITS


# ---------------------------------------------------------------------------
# Guarded-commit annotation self-check (host-clean — no heavy import)
# ---------------------------------------------------------------------------

def test_guarded_commits_include_p0_shas():
    """The single-source map carries the P0 boot self-restart shas, so the revert
    harness (Plan 05) has a real RED to turn for fe21a20 (the cancel-on-ready fix)."""
    shas = GUARDED_COMMITS["test_p0_boot_restart"]
    assert "fe21a20" in shas, "missing the load-bearing cancel-on-ready fix sha fe21a20"
    assert "be52083" in shas, "missing the MCP init_timeout floor sha be52083"


# ---------------------------------------------------------------------------
# (a) ARMED-WITH-BOUND — run() arms the whole-boot watchdog before boot work
# ---------------------------------------------------------------------------

@pytest.mark.requires_deps
def test_boot_watchdog_armed_with_configured_bound(monkeypatch):
    """run_ui.run() arms faulthandler.dump_traceback_later(BOOT_WATCHDOG_SECONDS,
    exit=True) BEFORE any boot work, using the configured (floored) bound."""
    import faulthandler

    import run_ui

    armed: dict = {"calls": []}

    def _spy_arm(timeout, *args, **kwargs):
        armed["calls"].append((timeout, args, kwargs))

    # Spy the arm; the real timer is never scheduled (spy captures instead).
    monkeypatch.setattr(faulthandler, "dump_traceback_later", _spy_arm, raising=True)
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: None, raising=True)

    # Stop the boot the instant AFTER the arm: run_migration_checks() is run()'s
    # first boot step, so raising here proves the arm precedes any boot work.
    def _stop_boot():
        raise RuntimeError("halt boot immediately after arm (test)")

    monkeypatch.setattr(run_ui, "run_migration_checks", _stop_boot, raising=True)

    with pytest.raises(RuntimeError, match="halt boot immediately after arm"):
        run_ui.run()

    assert armed["calls"], "run() must arm the whole-boot watchdog before boot work"
    timeout, _args, kwargs = armed["calls"][0]
    assert timeout == run_ui.BOOT_WATCHDOG_SECONDS, (
        f"watchdog armed with {timeout}s, expected the configured bound "
        f"{run_ui.BOOT_WATCHDOG_SECONDS}s"
    )
    assert run_ui.BOOT_WATCHDOG_SECONDS >= 30, (
        "the configured bound is floored at 30s (A0_BOOT_WATCHDOG_SECONDS minimum)"
    )
    # exit=True is what turns a wedged boot into os._exit(1) → supervisor self-restart.
    assert kwargs.get("exit") is True, (
        "watchdog must be armed with exit=True so a wedged boot self-restarts"
    )


# ---------------------------------------------------------------------------
# (b) READY CANCELS — the fe21a20 lock: mark_ready() disarms the watchdog
# ---------------------------------------------------------------------------

def _make_monitor():
    from helpers.server_startup import StartupMonitor

    return StartupMonitor(
        bind_host="0.0.0.0",
        probe_host="127.0.0.1",
        port=80,
        attempt=1,
        max_attempts=1,
        timeout_seconds=90,
    )


@pytest.mark.requires_deps
def test_mark_ready_cancels_boot_watchdog(monkeypatch):
    """Driving the ready path (StartupMonitor.mark_ready) cancels the faulthandler
    boot watchdog — the load-bearing fe21a20 fix. Reverting fe21a20 removes the
    cancel from mark_ready → a slow-but-healthy boot would be self-killed → RED."""
    import faulthandler

    calls = {"cancel": 0}
    monkeypatch.setattr(
        faulthandler,
        "cancel_dump_traceback_later",
        lambda: calls.__setitem__("cancel", calls["cancel"] + 1),
        raising=True,
    )

    monitor = _make_monitor()
    monitor.mark_ready("health_probe")

    assert calls["cancel"] >= 1, (
        "mark_ready() must cancel the faulthandler boot watchdog so a slow-but-healthy "
        "boot is not killed (fe21a20 / Pitfall 2)"
    )


# ---------------------------------------------------------------------------
# (b) HANG DOES NOT CANCEL — the watchdog stays armed when init never readies
# ---------------------------------------------------------------------------

@pytest.mark.requires_deps
def test_hung_init_does_not_cancel_watchdog(monkeypatch):
    """When init hangs, mark_ready is never reached, so the watchdog is NOT cancelled
    — it stays armed to fire (os._exit(1) → self-restart). Constructing a monitor and
    never marking it ready must leave cancel un-invoked."""
    import faulthandler

    calls = {"cancel": 0}
    monkeypatch.setattr(
        faulthandler,
        "cancel_dump_traceback_later",
        lambda: calls.__setitem__("cancel", calls["cancel"] + 1),
        raising=True,
    )

    monitor = _make_monitor()
    # Simulate a hung boot: readiness is never reached (mark_ready NOT called).
    assert monitor.is_ready() is False, "a hung boot must not report ready"
    assert calls["cancel"] == 0, (
        "the whole-boot watchdog must stay ARMED during a hang (cancel only fires on "
        "the ready path) so a wedged boot self-restarts"
    )
