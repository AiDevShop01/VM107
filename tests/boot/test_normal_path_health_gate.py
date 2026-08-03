"""Phase 132 Plan 01 — SC-3 RED unit test (normal-path health-gate + relaunch).

Today the NORMAL boot branch of `docker_run_ui()` (self_update_manager.py else-branch,
~:1196) launches run_ui.py with NO health gate and simply waits on the process. The
update path already health-gates via `wait_for_health`; this test asserts the same gate
lands on the normal path with a bounded relaunch: an unhealthy first launch is terminated
and a second launch is attempted.

The module lives under docker/run/fs/exe/ (not on the default import path), so it is
loaded via importlib.util.spec_from_file_location inside the test body. RED until Wave 2
(132-03) adds the relaunch loop. Marked slow because it exercises the full docker_run_ui
control flow.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_SUM_PATH = _VM107_ROOT / "docker" / "run" / "fs" / "exe" / "self_update_manager.py"


def _load_self_update_manager():
    """Load self_update_manager.py by file path (it is not on the import path)."""
    spec = importlib.util.spec_from_file_location(
        "self_update_manager_under_test", str(_SUM_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.slow
def test_normal_path_relaunches_on_unhealthy(monkeypatch):
    """docker_run_ui() normal path: unhealthy launch -> terminate -> relaunch (wait_for_health gate)."""
    m = _load_self_update_manager()

    launch_calls = {"n": 0}
    terminate_calls = {"n": 0}
    health_results = iter([(False, "unhealthy: first boot wedged"), (True, {"ok": True})])

    class _FakeProc:
        def __init__(self, idx):
            self.idx = idx

    def _fake_launch(repo_dir, logger):
        launch_calls["n"] += 1
        return _FakeProc(launch_calls["n"])

    def _fake_wait_for_health(process, **kwargs):
        try:
            return next(health_results)
        except StopIteration:
            return (True, {"ok": True})

    def _fake_terminate(process, timeout_seconds=20):
        terminate_calls["n"] += 1

    def _fake_wait_for_process(process):
        return 0

    # Force the NORMAL (else) branch: no pending update request.
    monkeypatch.setattr(m, "load_request_file", lambda: (None, ""), raising=True)
    monkeypatch.setattr(m, "launch_ui_process", _fake_launch, raising=True)
    monkeypatch.setattr(m, "wait_for_health", _fake_wait_for_health, raising=True)
    monkeypatch.setattr(m, "terminate_process", _fake_terminate, raising=True)
    monkeypatch.setattr(m, "wait_for_process", _fake_wait_for_process, raising=True)

    rc = m.docker_run_ui()

    # RED until 132-03 adds the health-gate + bounded relaunch on the normal path.
    assert launch_calls["n"] == 2, (
        "normal boot path must health-gate and relaunch once on an unhealthy first boot "
        f"(saw {launch_calls['n']} launches)"
    )
    assert terminate_calls["n"] == 1, (
        "the unhealthy first process must be terminated before relaunch "
        f"(saw {terminate_calls['n']} terminations)"
    )
    assert rc == 0
