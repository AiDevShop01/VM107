"""Phase 94-05 — Theme Engine docker-compose sibling-service smoke tests.

Per MEMORY.md ``feedback_mgmt_commands_need_compose_service``: any phase
that ships ``python -m management.commands.run_theme_engine`` MUST also
add the sibling service so the worker survives backend restarts.

This file mirrors the Wave-0 scaffold in the Dagster repo
(``Dagster/tests/test_docker_compose_phase94_siblings.py``) but lives in
VM107 alongside the docker-compose.yml it inspects — so the test is
runnable in either repo's pytest run.
"""

from __future__ import annotations

from pathlib import Path

import pytest


COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _load_compose():
    pytest.importorskip("yaml", reason="PyYAML required to parse docker-compose")
    import yaml

    if not COMPOSE_PATH.exists():
        pytest.fail(f"docker-compose not found at {COMPOSE_PATH}")
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def test_theme_engine_service_exists():
    compose = _load_compose()
    services = compose.get("services", {})
    assert "theme_engine" in services, (
        "94-05 must add the theme_engine sibling service per "
        "feedback_mgmt_commands_need_compose_service."
    )


def test_theme_engine_command_invokes_management_command():
    compose = _load_compose()
    svc = compose["services"]["theme_engine"]
    command = svc.get("command", "")
    if isinstance(command, list):
        command = " ".join(str(c) for c in command)
    assert "run_theme_engine" in command, (
        "theme_engine service must invoke management.commands.run_theme_engine "
        f"(got: {command!r})"
    )


def test_theme_engine_depends_on_redis():
    """Sibling service depends on the event-bus Redis (postgres is external in VM107)."""
    compose = _load_compose()
    svc = compose["services"]["theme_engine"]
    deps = svc.get("depends_on") or {}
    dep_names = list(deps) if isinstance(deps, (list, dict)) else []
    assert any("redis" in name for name in dep_names), (
        f"theme_engine must depend on a redis service (got depends_on={deps!r})"
    )


def test_theme_engine_uses_fail_fast_env_vars():
    """Env-driven-no-fallbacks lock — REDIS_HOST/REDIS_PORT must fail-fast."""
    compose = _load_compose()
    svc = compose["services"]["theme_engine"]
    env = svc.get("environment", {})
    # docker-compose env can be dict or list; normalise to dict.
    if isinstance(env, list):
        env = dict(e.split("=", 1) for e in env if "=" in e)
    redis_host = env.get("REDIS_HOST", "")
    redis_port = env.get("REDIS_PORT", "")
    assert ":?" in str(redis_host), (
        f"REDIS_HOST must use ${{VAR:?msg}} fail-fast (got: {redis_host!r})"
    )
    assert ":?" in str(redis_port), (
        f"REDIS_PORT must use ${{VAR:?msg}} fail-fast (got: {redis_port!r})"
    )


def test_theme_engine_has_healthcheck():
    compose = _load_compose()
    svc = compose["services"]["theme_engine"]
    hc = svc.get("healthcheck", {})
    assert hc, "theme_engine must have a healthcheck for sibling-service liveness"
    test = hc.get("test", [])
    if isinstance(test, list):
        test = " ".join(str(t) for t in test)
    assert "run_theme_engine" in test, (
        f"healthcheck must grep for run_theme_engine (got: {test!r})"
    )
