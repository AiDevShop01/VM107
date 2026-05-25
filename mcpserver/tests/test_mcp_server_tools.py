"""Phase 67 Plan 12 — FastMCP server + 2 tools registration tests (Task 1).

Covers:
- Env-driven config + fail-fast on missing env vars (Phase 47.3 lock).
- FastMCP server boots when all env vars present.
- mission.close.journal_prompts registered + callable + routes to VM100.
- mission.close.surfaced_lesson registered + callable + routes to VM100.
- Both tools surface VM100 errors (5xx → raises) so MCP client can react.
- Capability YAML at VM107/registry/tool/vm107.mcp_server.yaml parses
  with required Phase 47.6 keys.
- docker-compose.yml has fail-fast ${VAR:?msg} syntax for all new env vars.

NOTE: Tests intentionally mock VM100 responses via httpx.MockTransport —
the VM100 `/api/mission-control/close/reflection-prompts` proxy endpoint
ships in Plan 13 (this plan's <success_criteria> calls it out explicitly).
End-to-end real-data validation lives in Plan 13.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import httpx
import pytest
import yaml

# ---------------------------------------------------------------------------
# Constants + fixtures
# ---------------------------------------------------------------------------

VM107_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = VM107_ROOT.parent
CAPABILITY_YAML_PATH = VM107_ROOT / "registry" / "tool" / "vm107.mcp_server.yaml"
DOCKER_COMPOSE_PATH = VM107_ROOT / "docker-compose.yml"
REQUIREMENTS_PATH = VM107_ROOT / "requirements.txt"

_REQUIRED_ENV = {
    "VM107_MCP_JWKS_URI": "https://example.com/.well-known/jwks.json",
    "VM107_MCP_ISSUER": "fingpt-vm100",
    "VM107_MCP_AUDIENCE": "fingpt-mcp-clients",
    "VM107_MCP_PORT": "50091",
    "VM100_BASE_URL": "http://vm100-backend:8000",
    "VM100_INTERNAL_TOKEN": "test-internal-token-abc123",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    """Stamp all required env vars + optional overrides."""
    env = dict(_REQUIRED_ENV)
    env.update(overrides)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _clear_server_module() -> None:
    """Drop cached mcpserver imports so env-var changes re-trigger module load."""
    for key in list(sys.modules.keys()):
        if key == "mcpserver" or key.startswith("mcpserver."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# 1. Requirements pin (Pitfall 10)
# ---------------------------------------------------------------------------


def test_requirements_pins_fastmcp_in_v3_range() -> None:
    """fastmcp must be pinned >=3.2,<4 per Plan 12 Pitfall 10 mitigation."""
    content = REQUIREMENTS_PATH.read_text()
    # Match either bare `fastmcp>=3.2,<4` or any line specifying a 3.x range
    lines = [line.strip() for line in content.splitlines() if line.strip().startswith("fastmcp")]
    assert lines, "fastmcp must appear in requirements.txt"
    pin = lines[0]
    assert "3." in pin and "<4" in pin, (
        f"fastmcp must be pinned to the 3.x range (Pitfall 10); got: {pin!r}"
    )


# ---------------------------------------------------------------------------
# 2. Fail-fast env discipline (Phase 47.3 lock — no fallback defaults)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", list(_REQUIRED_ENV.keys()))
def test_server_module_fails_fast_when_required_env_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """Importing mcpserver.server must raise when ANY required env var is missing.

    No `os.getenv("X", "default")` fallbacks allowed (CLAUDE.md env-driven
    config lock). Missing env => KeyError or ImportError surfaced at module
    import / first-access time — fail-fast beats silent misconfiguration.
    """
    _clear_server_module()
    _set_env(monkeypatch, **{missing: None})

    with pytest.raises((KeyError, RuntimeError, ImportError, OSError, ValueError)):
        # Importing the server module + its tool modules must trip on the
        # missing env var. Some env vars are read by tools/, some by server —
        # we exercise the full module graph by importing both.
        importlib.import_module("mcpserver.server")
        importlib.import_module("mcpserver.tools")


# ---------------------------------------------------------------------------
# 3. FastMCP boots with full env present
# ---------------------------------------------------------------------------


def test_server_boots_with_full_env_and_registers_two_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all env vars present, FastMCP server boots + tool decorators register."""
    _clear_server_module()
    _set_env(monkeypatch)

    server_mod = importlib.import_module("mcpserver.server")
    # Importing tools/ executes the @mcp.tool decorators
    importlib.import_module("mcpserver.tools")

    mcp = getattr(server_mod, "mcp", None)
    assert mcp is not None, "mcpserver.server must export `mcp` (FastMCP instance)"

    # FastMCP API surface check — 3.x exposes async list_tools()
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "mission.close.journal_prompts" in names, (
        f"Expected mission.close.journal_prompts to be registered; got {names}"
    )
    assert "mission.close.surfaced_lesson" in names, (
        f"Expected mission.close.surfaced_lesson to be registered; got {names}"
    )


# ---------------------------------------------------------------------------
# 4. Tool routes to VM100 via httpx with bearer auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journal_prompts_tool_calls_vm100_with_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mission.close.journal_prompts must call VM100 with Bearer auth header."""
    _clear_server_module()
    _set_env(monkeypatch)
    importlib.import_module("mcpserver.server")
    tool_mod = importlib.import_module("mcpserver.tools.close_journal_prompts")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "set_id": "rfp-set-abc",
                "account_id": 42,
                "selected_prompts": [],
                "rejected_candidates": [],
                "reflection_set_coherence_score": 0.0,
                "generated_at": "2026-05-25T12:00:00Z",
            },
        )

    # Patch httpx.AsyncClient to use MockTransport
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tool_mod.httpx, "AsyncClient", patched_async_client)

    result = await tool_mod.mission_close_journal_prompts(account_id=42, date="2026-05-25")

    assert captured["method"] == "GET"
    assert "/api/mission-control/close/reflection-prompts" in captured["url"]
    assert "account_id=42" in captured["url"]
    assert "date=2026-05-25" in captured["url"]
    assert captured["auth"] == f"Bearer {_REQUIRED_ENV['VM100_INTERNAL_TOKEN']}"
    assert result["set_id"] == "rfp-set-abc"
    assert result["account_id"] == 42


@pytest.mark.asyncio
async def test_surfaced_lesson_tool_calls_vm100_with_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mission.close.surfaced_lesson must call VM100 with Bearer auth header."""
    _clear_server_module()
    _set_env(monkeypatch)
    importlib.import_module("mcpserver.server")
    tool_mod = importlib.import_module("mcpserver.tools.close_surfaced_lesson")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "lesson_id": "lesson-xyz",
                "account_id": 42,
                "session_date": "2026-05-25",
                "title": "Test lesson",
                "body": "Test body",
                "pattern_name": "test_pattern",
                "behavioral_target": "Test target",
                "confidence_score": 0.75,
                "supporting_trade_ids": [],
                "originating_discipline_flags": [],
                "fallback_used": False,
                "fallback_source_date": None,
                "banner_text": None,
                "_demo": False,
                "degraded_reason": None,
                "privacy_transform_applied": True,
                "privacy_transform_version": "v1",
                "privacy_context": None,
                "generated_at": "2026-05-25T12:00:00Z",
            },
        )

    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tool_mod.httpx, "AsyncClient", patched_async_client)

    result = await tool_mod.mission_close_surfaced_lesson(account_id=42, date="2026-05-25")

    assert captured["method"] == "GET"
    assert "/api/mission-control/surfaced-lesson" in captured["url"]
    assert "account_id=42" in captured["url"]
    assert "date=2026-05-25" in captured["url"]
    assert captured["auth"] == f"Bearer {_REQUIRED_ENV['VM100_INTERNAL_TOKEN']}"
    assert result["lesson_id"] == "lesson-xyz"
    assert result["_demo"] is False


@pytest.mark.asyncio
async def test_journal_prompts_raises_on_vm100_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VM100 500 must raise from the MCP tool so client sees the error."""
    _clear_server_module()
    _set_env(monkeypatch)
    importlib.import_module("mcpserver.server")
    tool_mod = importlib.import_module("mcpserver.tools.close_journal_prompts")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream error")

    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tool_mod.httpx, "AsyncClient", patched_async_client)

    with pytest.raises(httpx.HTTPStatusError):
        await tool_mod.mission_close_journal_prompts(account_id=42, date="2026-05-25")


@pytest.mark.asyncio
async def test_surfaced_lesson_raises_on_vm100_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VM100 500 must raise from the surfaced_lesson MCP tool too."""
    _clear_server_module()
    _set_env(monkeypatch)
    importlib.import_module("mcpserver.server")
    tool_mod = importlib.import_module("mcpserver.tools.close_surfaced_lesson")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream error")

    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tool_mod.httpx, "AsyncClient", patched_async_client)

    with pytest.raises(httpx.HTTPStatusError):
        await tool_mod.mission_close_surfaced_lesson(account_id=42, date="2026-05-25")


# ---------------------------------------------------------------------------
# 5. Capability YAML
# ---------------------------------------------------------------------------


def test_capability_yaml_exists_and_validates() -> None:
    """VM107/registry/tool/vm107.mcp_server.yaml must exist + carry Phase 47.6 keys."""
    assert CAPABILITY_YAML_PATH.exists(), (
        f"Capability YAML missing: {CAPABILITY_YAML_PATH}"
    )
    body = yaml.safe_load(CAPABILITY_YAML_PATH.read_text())

    assert body["id"] == "vm107.mcp_server"
    assert body["type"] == "tool"
    assert "mission.close.journal_prompts" in body.get("outputs", []), (
        f"outputs must include mission.close.journal_prompts; got {body.get('outputs')}"
    )
    assert "mission.close.surfaced_lesson" in body.get("outputs", [])
    # Phase 47.6 standard keys
    assert "description" in body and body["description"]
    assert "dependencies" in body
    # Health declaration (per <interfaces> block)
    assert "health" in body
    # Reflection_prompt + surfaced_lesson must be listed as upstream deps
    deps_str = yaml.safe_dump(body["dependencies"])
    assert "vm107.reflection_prompt" in deps_str
    assert (
        "surfaced_lesson" in deps_str
    ), "Must declare dependency on the VM100 surfaced_lesson endpoint"


# ---------------------------------------------------------------------------
# 6. Docker compose env additions (fail-fast syntax)
# ---------------------------------------------------------------------------


def test_docker_compose_has_failfast_env_for_mcp_vars() -> None:
    """docker-compose.yml vm107 service must declare all new env vars with ${VAR:?msg} fail-fast."""
    content = DOCKER_COMPOSE_PATH.read_text()
    # Each of these MUST appear with the :? fail-fast operator
    failfast_vars = [
        "VM107_MCP_JWKS_URI",
        "VM107_MCP_ISSUER",
        "VM107_MCP_AUDIENCE",
        "VM107_MCP_PORT",
        "VM100_BASE_URL",
        "VM100_INTERNAL_TOKEN",
    ]
    for var in failfast_vars:
        # The literal pattern `${VAR:?` (any error message) must be present
        assert f"${{{var}:?" in content, (
            f"docker-compose.yml must declare {var} with fail-fast ${{VAR:?msg}} syntax"
        )

    # The MCP port must also be exposed as a host port mapping. Either the
    # bare `${VM107_MCP_PORT}` or the fail-fast `${VM107_MCP_PORT:?msg}` form
    # is acceptable in the ports: list; the fail-fast form is strictly stricter.
    assert (
        "${VM107_MCP_PORT}" in content or "${VM107_MCP_PORT:?" in content
    ), "docker-compose.yml must expose ${VM107_MCP_PORT} as a port mapping"
