"""Phase 89.2 Wave 0 — discovery env wiring scaffolding tests (REQ-89.2-5, REQ-89.2-6).

These tests target two env-driven wiring requirements:

  REQ-89.2-5: DISCOVERY_POSTGRES_URL present in VM107 .env.local, pointing at
              tradetracker_analytics (the analytics DB used for discovery
              proposals). NEO4J_URI present (default bolt://192.168.1.105:7687).
              Landed by Phase 89.2 Plan 02.

  REQ-89.2-6: VM107_AGENT_URL wired in the canonical Dagster 3-place pattern:
              (1) .env, (2) docker-compose.yml service blocks (dagster_webserver
              and dagster_daemon at minimum — ≥ 2 occurrences), (3) dagster.yaml
              run_launcher env_vars list or documentation comment.
              Landed by Phase 89.2 Plan 06.

All 3 tests are xfail stubs at Wave 0 — they exist so Plan 02 / Plan 06 can
point their `<automated>` verify commands at real test targets (Nyquist
compliance). Once the env edits land, xfails flip to xpass and Plan 02/06
can rewrite the bodies to strict assertions.

Per project locks:
  - No live env reads, no subprocess, no Docker — pure source-text inspection
    via pathlib.Path.read_text(). Tests are runnable in any CI / quick-run loop.
  - Skip cleanly on FileNotFoundError so the suite works in cloned environments
    that don't have the full multi-repo tree.
  - No `os.getenv("X", "default")` fallback patterns — fail-fast at startup
    over silent misconfiguration (FinGPT project lock).
"""
from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.phase89


# ─── Module constants — absolute paths (FinGPT lives on the dev Mac) ─────────

VM107_ENV_LOCAL = pathlib.Path("/Volumes/ HardDrive/FinGPT/VM107/.env.local")
DAGSTER_ENV = pathlib.Path("/Volumes/ HardDrive/FinGPT/Dagster/.env")
DAGSTER_COMPOSE = pathlib.Path("/Volumes/ HardDrive/FinGPT/Dagster/docker-compose.yml")
DAGSTER_YAML = pathlib.Path(
    "/Volumes/ HardDrive/FinGPT/Dagster/dagster_home/dagster.yaml"
)


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 02 — DISCOVERY_POSTGRES_URL not yet added to VM107/.env.local",
    strict=False,
)
def test_discovery_postgres_url_present():
    """VM107/.env.local contains DISCOVERY_POSTGRES_URL pointing at tradetracker_analytics.

    Plan 02 adds the line. Wave 0 stub asserts the line + DB name pattern via
    pure source-text inspection (no live env load — keeps test deterministic).
    """
    if not VM107_ENV_LOCAL.exists():
        pytest.skip(f"VM107/.env.local not found at {VM107_ENV_LOCAL}")

    env_text = VM107_ENV_LOCAL.read_text()
    discovery_lines = [
        line for line in env_text.splitlines()
        if line.strip().startswith("DISCOVERY_POSTGRES_URL=")
    ]

    assert discovery_lines, (
        "VM107/.env.local must contain a line starting with "
        "'DISCOVERY_POSTGRES_URL=' (Phase 89.2 Plan 02 / REQ-89.2-5)"
    )

    # The value must point at the tradetracker_analytics DB (where discovery
    # proposals live — separate from the tradetracker app DB).
    discovery_line = discovery_lines[0]
    assert "tradetracker_analytics" in discovery_line, (
        f"DISCOVERY_POSTGRES_URL must point at tradetracker_analytics DB, "
        f"got: {discovery_line!r}"
    )


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 02 — NEO4J_URI presence not yet validated",
    strict=False,
)
def test_neo4j_uri_present_in_vm107_env():
    """VM107/.env.local contains NEO4J_URI (default bolt://192.168.1.105:7687).

    Plan 02 ensures the line exists for the EdgeProposer Neo4j write path.
    """
    if not VM107_ENV_LOCAL.exists():
        pytest.skip(f"VM107/.env.local not found at {VM107_ENV_LOCAL}")

    env_text = VM107_ENV_LOCAL.read_text()
    neo4j_lines = [
        line for line in env_text.splitlines()
        if line.strip().startswith("NEO4J_URI=")
    ]

    assert neo4j_lines, (
        "VM107/.env.local must contain a line starting with 'NEO4J_URI=' "
        "(Phase 89.2 Plan 02 / REQ-89.2-5 — default value bolt://192.168.1.105:7687)"
    )


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 06 — VM107_AGENT_URL 3-place wiring not yet complete",
    strict=False,
)
def test_vm107_agent_url_wired_3_places():
    """VM107_AGENT_URL wired in Dagster (.env, docker-compose.yml, dagster.yaml).

    The Dagster 3-place lock pattern (same shape as BELIEF_STORE_POSTGRES_URL):
      1. Dagster/.env contains a `VM107_AGENT_URL=...` line.
      2. Dagster/docker-compose.yml has `VM107_AGENT_URL: ${VM107_AGENT_URL}`
         in BOTH dagster_webserver and dagster_daemon service `environment:`
         blocks — at minimum ≥ 2 occurrences in the file.
      3. Dagster/dagster_home/dagster.yaml references VM107_AGENT_URL (either
         in `run_launcher.env_vars` list or via a documentation comment per
         the project pattern).

    Plan 06 lands all 3 edits. Wave 0 stub keeps the test target reachable.
    """
    missing: list[str] = []
    for path in (DAGSTER_ENV, DAGSTER_COMPOSE, DAGSTER_YAML):
        if not path.exists():
            missing.append(str(path))
    if missing:
        pytest.skip(f"Required Dagster file(s) not found: {missing}")

    env_text = DAGSTER_ENV.read_text()
    compose_text = DAGSTER_COMPOSE.read_text()
    dagster_yaml_text = DAGSTER_YAML.read_text()

    # Place 1: Dagster/.env
    env_lines = [
        line for line in env_text.splitlines()
        if line.strip().startswith("VM107_AGENT_URL=")
    ]
    assert env_lines, (
        "Dagster/.env must contain a line starting with 'VM107_AGENT_URL=' "
        "(Phase 89.2 Plan 06 / REQ-89.2-6, 3-place lock #1)"
    )

    # Place 2: Dagster/docker-compose.yml — must appear in ≥ 2 service blocks
    # (dagster_webserver and dagster_daemon at minimum).
    compose_occurrences = compose_text.count("VM107_AGENT_URL")
    assert compose_occurrences >= 2, (
        f"Dagster/docker-compose.yml must reference VM107_AGENT_URL in BOTH "
        f"dagster_webserver and dagster_daemon environment blocks (≥ 2 "
        f"occurrences). Found {compose_occurrences}. "
        f"(Phase 89.2 Plan 06 / REQ-89.2-6, 3-place lock #2)"
    )

    # Place 3: Dagster/dagster_home/dagster.yaml — comment or env_vars entry
    assert "VM107_AGENT_URL" in dagster_yaml_text, (
        "Dagster/dagster_home/dagster.yaml must reference VM107_AGENT_URL "
        "(comment or run_launcher.env_vars entry). "
        "(Phase 89.2 Plan 06 / REQ-89.2-6, 3-place lock #3)"
    )
