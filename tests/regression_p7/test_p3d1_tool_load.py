"""Phase 139 P7 — P3-D1 tool-load masking regression (SC-1).

Guards (single-source `guarded_commits.GUARDED_COMMITS['test_p3d1_tool_load']`):
  0321329  — feat(135-02): FailedToLoad sentinel + tri-state selection, so a tool
             file that EXISTS on the resolution path but fails to load is
             distinguishable from a genuinely-missing name (no more masking a broken
             tool as Unknown).
  dcbe600  — feat(138-05): extract `get_tool` into `core/agents/tool_dispatch.py`
             (the P6 seam this test drives; behavior identical).

What this locks (the tri-state, driven through the P6-extracted seam):
  * a tool file that EXISTS but raises on load  -> FailedToLoad (NOT Unknown), with a
    WARNING carrying the tool name + resolved path + traceback (exc_info);
  * a name with NO file anywhere                -> Unknown (unchanged BUG-17 behavior);
  * the failed-load refusal is DISTINCT from the not-found refusal and leaks no
    traceback/infra detail (T-135-02).
  Reverting 0321329 collapses the middle state back to Unknown (masking a broken tool)
  -> the FailedToLoad assertion goes RED.

Injected-fault posture (D-10): a deliberately syntax-broken tool file is written onto
a tmp resolution path and `subagents.get_paths` is monkeypatched to surface it — no
real tool file is touched, no shared dependency is stopped.

Tier-2 note: `@pytest.mark.requires_deps` — the seam pulls the `agent`/`tools` import
graph (litellm et al. on the pinned deps), so this runs under the Tier-2 venv
(VM107/.venv, python3.12). All heavy imports are DEFERRED into the fixture/test bodies
so host-clean collection under `-m "not requires_deps"` deselects without a
ModuleNotFoundError (no top-level heavy import).
"""
from __future__ import annotations

import logging
import os
import textwrap

import pytest

from tests.regression_p7.guarded_commits import GUARDED_COMMITS

_BROKEN_NAME = "phase139_broken_tool_xyz"
_MISSING_NAME = "definitely_not_a_tool_xyz"
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REAL_PROMPTS_DIR = os.path.join(_REPO_ROOT, "prompts")


def test_guarded_commits_include_p3d1_shas():
    """The single-source map carries the P3-D1 shas (host-clean self-check)."""
    shas = GUARDED_COMMITS["test_p3d1_tool_load"]
    assert "0321329" in shas, "missing the FailedToLoad sentinel fix sha 0321329"
    assert "dcbe600" in shas, "missing the get_tool extraction sha dcbe600"


def _write_broken_tool(tmp_path) -> str:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    broken = tools_dir / f"{_BROKEN_NAME}.py"
    # Deliberate syntax error (unclosed paren + missing colon) -> exec_module raises.
    broken.write_text(
        textwrap.dedent(
            """
            from helpers.tool import Tool

            class Broken(Tool          # <-- intentional syntax error
                async def execute(self, **kwargs):
                    pass
            """
        )
    )
    return str(broken)


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    """Point `subagents.get_paths` at a tmp tools dir holding one broken tool file.

    Returns the broken file's absolute path so tests can assert the WARN carries it.
    Heavy imports are deferred to here (fixture body) so host-clean collection stays
    clean; this fixture is only ever instantiated by the requires_deps tests below.
    """
    from helpers import subagents

    broken_path = _write_broken_tool(tmp_path)

    def fake_get_paths(agent, *subpaths, must_exist_completely=True, **kw):
        # Flat tool lookup: ("tools", "<name>.py")
        if len(subpaths) == 2 and subpaths[0] == "tools":
            if subpaths[1] == f"{_BROKEN_NAME}.py":
                return [broken_path]  # file EXISTS on the path (but will fail to load)
            return []  # no file anywhere -> Unknown control case
        # BUG-17 recursive-glob roots: ("tools",) with must_exist_completely=False
        if subpaths == ("tools",):
            return [str(tmp_path / "tools")]
        # read_prompt resolves against the real prompts/ dir
        if subpaths == ("prompts",):
            return [_REAL_PROMPTS_DIR]
        return []

    monkeypatch.setattr(subagents, "get_paths", fake_get_paths)
    return broken_path


def _fake_agent():
    """Minimal Agent duck: get_tool/read_prompt reach the filesystem ONLY through
    the monkeypatched `subagents.get_paths`, so the fake just needs `read_prompt`
    for the sentinel's execute() to render its refusal prompt."""
    from agent import Agent

    class _FakeAgent:
        read_prompt = Agent.read_prompt

    return _FakeAgent()


def _get_tool(name: str):
    """Drive the P6-extracted seam `core.agents.tool_dispatch.get_tool` (dcbe600)."""
    from core.agents.tool_dispatch import get_tool

    return get_tool(
        _fake_agent(),
        name=name,
        method=None,
        args={},
        message="",
        loop_data=None,
    )


@pytest.mark.requires_deps
def test_broken_tool_returns_failed_to_load_with_warn(resolver, caplog):
    """Broken-but-present tool -> FailedToLoad + WARN carrying name + path + traceback.
    Reverting 0321329 collapses this to Unknown (masking) -> RED."""
    from tools.failed_to_load import FailedToLoad
    from tools.unknown import Unknown

    with caplog.at_level(logging.WARNING):
        result = _get_tool(_BROKEN_NAME)

    assert isinstance(result, FailedToLoad), (
        "a tool file that exists-but-fails-to-load must return FailedToLoad, got "
        f"{type(result).__name__} (masking regression — 0321329 reverted?)"
    )
    assert not isinstance(result, Unknown), "FailedToLoad must be distinct from Unknown"

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    hits = [
        r
        for r in warn_records
        if _BROKEN_NAME in r.getMessage() and os.path.basename(resolver) in r.getMessage()
    ]
    assert hits, (
        "expected a WARNING carrying the tool name + resolved path; got "
        f"{[r.getMessage() for r in warn_records]}"
    )
    assert hits[0].exc_info is not None, "WARN must carry the traceback via exc_info"
    assert hits[0].exc_info[0] is not None, "exc_info must hold a real exception type"


@pytest.mark.requires_deps
def test_failed_to_load_refusal_is_distinct(resolver):
    """FailedToLoad.execute() renders fw.tool_failed_to_load.md, NOT fw.tool_not_found.md,
    and leaks no traceback/infra detail (T-135-02)."""
    import asyncio

    from agent import Agent

    result = _get_tool(_BROKEN_NAME)
    resp = asyncio.run(result.execute())
    text = resp.message

    assert _BROKEN_NAME in text, "refusal must name the tool via {{tool_name}}"
    not_found = Agent.read_prompt(
        _fake_agent(), "fw.tool_not_found.md", tool_name=_BROKEN_NAME, tools_prompt=""
    )
    assert text != not_found, "failed-to-load refusal must differ from the not-found refusal"
    assert "not found" not in text.lower(), "must NOT say 'not found' (the tool exists)"
    assert "Traceback" not in text and 'File "' not in text, "no traceback/infra leak"


@pytest.mark.requires_deps
def test_missing_name_returns_unknown(resolver):
    """Control: a name with NO file anywhere still returns Unknown (unchanged)."""
    from tools.failed_to_load import FailedToLoad
    from tools.unknown import Unknown

    result = _get_tool(_MISSING_NAME)
    assert isinstance(result, Unknown), (
        f"a name with no file must stay Unknown, got {type(result).__name__}"
    )
    assert not isinstance(result, FailedToLoad)
