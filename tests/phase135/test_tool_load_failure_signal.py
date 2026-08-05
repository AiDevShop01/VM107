"""Phase 135 (P3 — D1) — tool-load-failure signal.

A tool file that EXISTS on the ``get_tool`` resolution path but fails to load must
return a distinct ``FailedToLoad`` sentinel (NOT a generic ``Unknown``), log the
caught exception at WARNING with the tool name + resolved path + traceback
(``exc_info``), and refuse via ``fw.tool_failed_to_load.md`` (distinct from
``fw.tool_not_found.md``). A tool name with NO file anywhere still returns
``Unknown`` (unchanged BUG-17-preserving behavior).

Injected-fault posture (D-10): a deliberately broken (syntax-error) tool file is
written onto a tmp resolution path and ``subagents.get_paths`` is monkeypatched to
surface it — no real tool file is touched, no shared dependency is stopped. This
test is RED at collection until plans' Tasks 2-3 land ``tools.failed_to_load`` and
wire ``agent.get_tool`` (the import below fails until then — that IS the RED signal).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import textwrap

import pytest

# Repo root on sys.path (conftest also does this; explicit keeps the module importable standalone).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent import Agent  # noqa: E402
from helpers import subagents  # noqa: E402
from tools.failed_to_load import FailedToLoad  # noqa: E402  (RED until Task 2/3 land)
from tools.unknown import Unknown  # noqa: E402

_BROKEN_NAME = "phase135_broken_tool_xyz"
_MISSING_NAME = "definitely_not_a_tool_xyz"
_REAL_PROMPTS_DIR = os.path.join(_REPO_ROOT, "prompts")


class _FakeAgent:
    """Minimal Agent duck.

    ``get_tool`` and ``read_prompt`` reach the filesystem ONLY through
    ``subagents.get_paths`` (monkeypatched by the ``resolver`` fixture), so the fake
    needs no config/context — it only has to carry ``read_prompt`` for the sentinel's
    ``execute()`` to render its refusal prompt.
    """

    read_prompt = Agent.read_prompt


def _write_broken_tool(tmp_path) -> str:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    broken = tools_dir / f"{_BROKEN_NAME}.py"
    # Deliberate syntax error (unclosed paren + missing colon) -> exec_module raises SyntaxError.
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
    """Point ``subagents.get_paths`` at a tmp tools dir holding one broken tool file.

    Returns the broken file's absolute path so tests can assert the WARN carries it.
    """
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
        # extension points etc. -> no extra machinery runs
        return []

    monkeypatch.setattr(subagents, "get_paths", fake_get_paths)
    return broken_path


def _get_tool(name: str):
    return Agent.get_tool(
        _FakeAgent(),
        name=name,
        method=None,
        args={},
        message="",
        loop_data=None,
    )


def test_broken_tool_returns_failed_to_load_with_warn(resolver, caplog):
    """Broken-but-present tool -> FailedToLoad + WARN carrying name + path + traceback."""
    with caplog.at_level(logging.WARNING):
        result = _get_tool(_BROKEN_NAME)

    assert isinstance(result, FailedToLoad), (
        "a tool file that exists-but-fails-to-load must return FailedToLoad, got "
        f"{type(result).__name__}"
    )
    assert not isinstance(result, Unknown), "FailedToLoad must be distinct from Unknown"

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    hits = [
        r
        for r in warn_records
        if _BROKEN_NAME in r.getMessage()
        and os.path.basename(resolver) in r.getMessage()
    ]
    assert hits, (
        "expected a WARNING carrying the tool name + resolved path; got "
        f"{[r.getMessage() for r in warn_records]}"
    )
    rec = hits[0]
    assert rec.exc_info is not None, "WARN must carry the traceback via exc_info (server-log only)"
    assert rec.exc_info[0] is not None, "exc_info must hold a real exception type"


def test_failed_to_load_refusal_is_distinct(resolver):
    """FailedToLoad.execute() renders fw.tool_failed_to_load.md, NOT fw.tool_not_found.md."""
    result = _get_tool(_BROKEN_NAME)
    resp = asyncio.run(result.execute())
    text = resp.message

    assert _BROKEN_NAME in text, "refusal must name the tool via {{tool_name}}"
    not_found = Agent.read_prompt(
        _FakeAgent(), "fw.tool_not_found.md", tool_name=_BROKEN_NAME, tools_prompt=""
    )
    assert text != not_found, "failed-to-load refusal must differ from the not-found refusal"
    assert "not found" not in text.lower(), "must NOT say 'not found' (the tool exists)"
    # T-135-02 no-leak: the prompt must never carry a raw traceback / infra detail.
    assert "Traceback" not in text and "File \"" not in text


def test_missing_name_returns_unknown(resolver):
    """Control: a name with NO file anywhere still returns Unknown (unchanged)."""
    result = _get_tool(_MISSING_NAME)
    assert isinstance(result, Unknown), (
        f"a name with no file must stay Unknown, got {type(result).__name__}"
    )
    assert not isinstance(result, FailedToLoad)
