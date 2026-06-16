"""Phase 87 Wave 4b — REQ-87-8 + LOCK-8 compose sibling-service guard.

Asserts that docker-compose.yml ships a vm107-macro-story-tracker sibling
service for the long-running APScheduler runner. Per
``feedback_mgmt_commands_need_compose_service``: every long-running worker
MUST ship as a docker-compose sibling service. Plan 74-03 lost the
observation pipeline by skipping this lock; this test prevents the
regression at CI time.

Survival of ``docker compose restart vm107-backend`` is verified by Plan
87-14 Wave 8 deploy gate (requires a live docker daemon — out of scope
for this unit test).

Deviation from Plan 87-08 reference test (Rule 3 Blocking):
The plan specified ``docker-compose.vm107.yml`` as a separate file. VM107
already ships ``docker-compose.yml`` with the canonical sibling-service
pattern (Phase 83 vm107-macro-emitter, Phase 85 Plan 10
vm107-macro-release-event-listener, Phase 85.1 Plan 03 vm107-task-dispatcher).
Adding a parallel ``docker-compose.vm107.yml`` would split-brain the
operational surface and the existing sibling services. The Plan 87-08
sibling service was added inline to the existing ``docker-compose.yml``;
this test asserts against that file accordingly.
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
        f"Plan 87-08 must extend {COMPOSE} with the sibling service"
    )


def test_compose_file_parses_as_yaml() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    assert isinstance(data, dict)
    assert "services" in data


def test_story_tracker_sibling_service_declared() -> None:
    """REQ-87-8: vm107-macro-story-tracker service required."""
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"].get("vm107-macro-story-tracker")
    assert svc is not None, (
        "REQ-87-8 / LOCK-8: vm107-macro-story-tracker sibling service "
        "missing from docker-compose.yml — long-running runner cannot ship "
        "as mgmt-command-only (Phase 74-03 lesson)."
    )


def test_story_tracker_sibling_uses_restart_policy() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-story-tracker"]
    assert svc.get("restart") == "unless-stopped", (
        "Sibling service MUST set restart: unless-stopped so it survives "
        "container crashes (LOCK-8)."
    )


def test_story_tracker_sibling_command_invokes_runner() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-story-tracker"]
    cmd = svc.get("command", "")
    if isinstance(cmd, list):
        cmd = " ".join(str(c) for c in cmd)
    assert "scripts.run_macro_story_tracker" in cmd or "run_macro_story_tracker" in cmd, (
        f"Sibling service command MUST invoke run_macro_story_tracker; got {cmd!r}"
    )


def test_story_tracker_sibling_healthcheck_wires_to_health_module() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-story-tracker"]
    hc = svc.get("healthcheck") or {}
    test = hc.get("test") or []
    if isinstance(test, str):
        test = [test]
    joined = " ".join(str(t) for t in test)
    assert "macro_story_tracker_health" in joined, (
        "Healthcheck MUST invoke scripts.macro_story_tracker_health so "
        "stale-tick detection (>90 min) triggers container recovery."
    )


def test_story_tracker_sibling_depends_on_vm107_backend() -> None:
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-story-tracker"]
    deps = svc.get("depends_on") or []
    # depends_on can be a list ["svc"] or a dict {"svc": {...}}.
    if isinstance(deps, dict):
        deps = list(deps.keys())
    # The VM107 backend service is named "vm107" (per docker-compose.yml inspection).
    # Phase 87-08 follows the macro_release_event_listener precedent which
    # depends on "vm107" (the agent-zero backend), not a separate
    # "vm107-backend" service that does not exist in this compose file.
    assert ("vm107" in deps) or ("vm107-backend" in deps), (
        f"Sibling service MUST depends_on the vm107 backend; got {deps}"
    )


def test_story_tracker_sibling_passes_required_env_to_runner() -> None:
    """Runner fails-fast on missing VM101_INTERNAL_BASE_URL + QDRANT_URL.

    The compose service must propagate those env vars (via env_file or
    inline environment block) so the sibling-service boot does not exit 1
    on first tick.
    """
    data = yaml.safe_load(COMPOSE.read_text())
    svc = data["services"]["vm107-macro-story-tracker"]
    env_file = svc.get("env_file") or []
    if isinstance(env_file, str):
        env_file = [env_file]
    env_block = svc.get("environment") or {}
    if isinstance(env_block, list):
        # convert list ["KEY=VAL"] form to dict
        env_block = {
            kv.split("=", 1)[0]: (kv.split("=", 1)[1] if "=" in kv else "")
            for kv in env_block
        }

    # The two required env vars: either passed inline OR resolved from .env*
    raw = COMPOSE.read_text()
    has_env_file = bool(env_file)
    has_vm101 = "VM101_INTERNAL_BASE_URL" in env_block or has_env_file
    has_qdrant = "QDRANT_URL" in env_block or has_env_file
    assert has_vm101, (
        "Sibling service MUST pass VM101_INTERNAL_BASE_URL "
        "(env_file or environment block)."
    )
    assert has_qdrant, (
        "Sibling service MUST pass QDRANT_URL "
        "(env_file or environment block)."
    )
    # And the compose file should reference both somewhere so the operator
    # sees the wiring even if env_file is doing the heavy lifting.
    assert "VM101_INTERNAL_BASE_URL" in raw
    assert "QDRANT_URL" in raw
