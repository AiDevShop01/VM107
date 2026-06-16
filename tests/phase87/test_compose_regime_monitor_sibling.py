"""Phase 87 Plan 10 — REQ-87-8 + LOCK-8 compose sibling-service guard.

Asserts that docker-compose.yml ships a ``vm107-macro-regime-monitor``
sibling service alongside Plan 87-08's ``vm107-macro-story-tracker``.
Per ``feedback_mgmt_commands_need_compose_service``: every long-running
worker MUST ship as a docker-compose sibling service. Plan 74-03 lost
the observation pipeline by skipping this lock; this test prevents the
regression at CI time.

Survival of ``docker compose restart vm107`` is verified by Plan 87-14
Wave 8 deploy gate (requires a live docker daemon — out of scope for
this unit test).

Deviation from Plan 87-10 reference test (Rule 3 Blocking):

  * The plan referenced ``docker-compose.vm107.yml`` as a separate file.
    VM107 already ships ``docker-compose.yml`` with the canonical
    sibling-service pattern (Phase 83 vm107-macro-emitter, Phase 85
    vm107-macro-release-event-listener, Phase 85.1 vm107-task-dispatcher,
    Phase 87 Plan 08 vm107-macro-story-tracker). Plan 87-08's deviation
    already established the precedent: append to the existing file
    instead of split-brained parallel compose files. This test asserts
    against ``docker-compose.yml`` accordingly.

  * The plan-spec'd "both siblings share &backend-env / &backend-volumes
    YAML anchors" test was adapted: Plan 87-08 did NOT introduce YAML
    anchors (the existing pre-87 sibling services do not use anchors
    either). Instead each sibling repeats its env_file + environment +
    volumes blocks explicitly. The "single source of truth" assertion is
    now: both siblings declare ``env_file: .env.local`` and the same
    ``restart: unless-stopped`` policy, and both invoke their runners
    via ``python -m scripts.*``.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml


pytestmark = pytest.mark.phase_87


# VM107 root is two parents up from this file (tests/phase87/<f>.py).
VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
COMPOSE = VM107_ROOT / "docker-compose.yml"


def test_compose_file_exists() -> None:
    assert COMPOSE.exists(), (
        f"Plan 87-10 must extend {COMPOSE} with the regime_monitor sibling"
    )


def test_compose_file_parses_as_yaml() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    assert "services" in data


def test_regime_monitor_sibling_service_declared() -> None:
    """REQ-87-8: vm107-macro-regime-monitor service required."""
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"].get("vm107-macro-regime-monitor")
    assert svc is not None, (
        "REQ-87-8 / LOCK-8: vm107-macro-regime-monitor sibling service "
        "missing from docker-compose.yml — long-running runner cannot "
        "ship as mgmt-command-only (Phase 74-03 lesson)."
    )


def test_regime_monitor_sibling_uses_restart_policy() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-regime-monitor"]
    assert svc.get("restart") == "unless-stopped", (
        "Sibling service MUST set restart: unless-stopped so it survives "
        "container crashes (LOCK-8)."
    )


def test_regime_monitor_sibling_command_invokes_runner() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-regime-monitor"]
    cmd = svc.get("command", "")
    if isinstance(cmd, list):
        cmd = " ".join(str(c) for c in cmd)
    assert (
        "scripts.run_macro_regime_monitor" in cmd
        or "run_macro_regime_monitor" in cmd
    ), (
        "Sibling service command MUST invoke run_macro_regime_monitor; "
        f"got {cmd!r}"
    )


def test_regime_monitor_sibling_healthcheck_wires_to_health_module() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-regime-monitor"]
    hc = svc.get("healthcheck") or {}
    test = hc.get("test") or []
    if isinstance(test, str):
        test = [test]
    joined = " ".join(str(t) for t in test)
    assert "macro_regime_monitor_health" in joined, (
        "Healthcheck MUST invoke scripts.macro_regime_monitor_health so "
        "stale-tick detection (>7h) triggers container recovery."
    )


def test_regime_monitor_sibling_depends_on_vm107_backend() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-regime-monitor"]
    deps = svc.get("depends_on") or []
    if isinstance(deps, dict):
        deps = list(deps.keys())
    assert ("vm107" in deps) or ("vm107-backend" in deps), (
        f"Sibling service MUST depends_on the vm107 backend; got {deps}"
    )


def test_regime_monitor_sibling_passes_required_env_vars() -> None:
    """Runner fails-fast on BELIEF_STORE_POSTGRES_URL +
    BELIEF_STORE_MONGO_URL + PHASE74_DISPATCHER_URL + VM101_INTERNAL_BASE_URL.

    Compose service must propagate those env vars (via env_file or inline
    environment block) so the sibling-service boot does not exit 1 on
    first tick.
    """
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-regime-monitor"]
    env_file = svc.get("env_file") or []
    if isinstance(env_file, str):
        env_file = [env_file]
    env_block = svc.get("environment") or {}
    if isinstance(env_block, list):
        env_block = {
            kv.split("=", 1)[0]: (kv.split("=", 1)[1] if "=" in kv else "")
            for kv in env_block
        }

    has_env_file = bool(env_file)
    required = [
        "BELIEF_STORE_POSTGRES_URL",
        "BELIEF_STORE_MONGO_URL",
        "PHASE74_DISPATCHER_URL",
        "VM101_INTERNAL_BASE_URL",
    ]
    raw = COMPOSE.read_text()
    for key in required:
        in_env_block = key in env_block
        assert in_env_block or has_env_file, (
            f"Sibling service MUST pass {key} (env_file or environment block)."
        )
        # And the compose file must reference it somewhere so the operator
        # can see the wiring even if env_file is doing the heavy lifting.
        assert key in raw, (
            f"{key} not referenced in docker-compose.yml — operator "
            "cannot see the wiring."
        )


def test_both_siblings_use_same_env_file_and_restart_policy() -> None:
    """Single-source-of-truth via .env.local (NOT YAML anchors per 87-08
    deviation). Both Phase 87 sibling services MUST agree on env_file
    + restart policy so deploy-time drift is caught at CI."""
    data = yaml.safe_load(COMPOSE.read_text())
    siblings = ("vm107-macro-story-tracker", "vm107-macro-regime-monitor")
    for name in siblings:
        svc = data["services"].get(name)
        assert svc is not None, f"sibling {name!r} missing from compose file"
        env_file = svc.get("env_file") or []
        if isinstance(env_file, str):
            env_file = [env_file]
        assert ".env.local" in env_file, (
            f"sibling {name!r} MUST source from .env.local — both Phase "
            "87 siblings agree on this file for single-source-of-truth."
        )
        assert svc.get("restart") == "unless-stopped", (
            f"sibling {name!r} MUST set restart: unless-stopped"
        )


def test_both_siblings_invoke_via_python_scripts_module() -> None:
    """Both Phase 87 sibling services MUST invoke their runner via
    ``python -m scripts.*`` (the Plan 87-08 scripts/ pattern that
    replaced the plan-spec'd management/commands/ paths)."""
    data = yaml.safe_load(COMPOSE.read_text())
    sibling_cmds = {
        "vm107-macro-story-tracker": "scripts.run_macro_story_tracker",
        "vm107-macro-regime-monitor": "scripts.run_macro_regime_monitor",
    }
    for name, expected in sibling_cmds.items():
        svc = data["services"][name]
        cmd = svc.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        assert expected in cmd, (
            f"sibling {name!r} command MUST invoke {expected}; got {cmd!r}"
        )
